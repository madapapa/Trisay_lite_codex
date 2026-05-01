import json
import asyncio
import shutil
from pathlib import Path
from uuid import uuid4

import aiofiles
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import create_session, delete_session, get_session, init_db, list_sessions, update_session
from .model_manager import delete_model, get_local_models_state, get_model_catalog_state, import_local_model, select_model, start_model_download, stop_model
from .paths import EXPORTS_DIR, FRONTEND_DIST_DIR, STORAGE_DIR, TRANSCRIPTS_DIR, UPLOADS_DIR, ensure_runtime_dirs
from .transcriber import TranscriptionError, calculate_transcript_metrics, clean_transcript_payload, transcribe_with_mlx

SUPPORTED_LANGUAGES = {"auto", "zh", "id"}

app = FastAPI(title="Trisay Lite API")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    ensure_runtime_dirs()
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_model=None)
def root():
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    return {
        "name": "Trisay Lite API",
        "status": "running",
        "frontend": "http://127.0.0.1:5174",
        "docs": "/docs",
    }


@app.get("/sessions")
def sessions() -> dict[str, object]:
    return {"items": list_sessions()}


@app.get("/models")
def models() -> dict[str, object]:
    return get_model_catalog_state()


@app.get("/models/local")
def local_models() -> dict[str, object]:
    return get_local_models_state()


def ensure_transcript_dir(session_id: str) -> Path:
    transcript_dir = TRANSCRIPTS_DIR / session_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    return transcript_dir


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def delete_file_if_safe(path_value: object, allowed_parent: Path) -> bool:
    if not path_value:
        return False

    path = Path(str(path_value))
    if not is_relative_to(path, allowed_parent) or not path.exists() or not path.is_file():
        return False

    path.unlink()
    return True


def delete_directory_if_safe(path: Path, allowed_parent: Path) -> bool:
    if not is_relative_to(path, allowed_parent) or not path.exists() or not path.is_dir():
        return False

    shutil.rmtree(path)
    return True


@app.post("/models/{model_id}/download")
def download_model(model_id: str) -> dict[str, object]:
    try:
        return start_model_download(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Model not found")


@app.post("/models/{model_id}/select")
def choose_model(model_id: str) -> dict[str, object]:
    try:
        return select_model(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Model not found")
    except FileNotFoundError:
        raise HTTPException(status_code=409, detail="Model is not installed")


@app.post("/models/{model_id}/stop")
def stop_active_model(model_id: str) -> dict[str, object]:
    return stop_model(model_id)


@app.delete("/models/{model_id}")
def remove_model(model_id: str) -> dict[str, object]:
    try:
        return delete_model(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Model not found")


@app.post("/models/local/import")
async def import_model_directory(model_id: str = Form(...), files: list[UploadFile] = File(...)) -> dict[str, object]:
    try:
        payload: list[tuple[str, bytes]] = []
        for file in files:
            relative_path = file.filename or ""
            content = await file.read()
            payload.append((relative_path, content))
        return import_local_model(model_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


def read_transcript_payload(transcript_path_value: object) -> tuple[str, dict[str, object] | None, dict[str, object] | None]:
    if not transcript_path_value:
        return "", None, None

    transcript_path = Path(str(transcript_path_value))
    if not transcript_path.exists():
        return "", None, None

    transcript_raw = transcript_path.read_text(encoding="utf-8")
    try:
        transcript_payload = json.loads(transcript_raw)
    except json.JSONDecodeError:
        return transcript_raw.strip(), None, None

    transcript_text = clean_transcript_payload(transcript_payload)
    metrics = transcript_payload.get("metrics")
    if not isinstance(metrics, dict):
        metrics = calculate_transcript_metrics(transcript_payload)
    return transcript_text, transcript_payload, metrics


@app.get("/sessions/{session_id}")
def session_detail(session_id: str) -> dict[str, object]:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    transcript_text = ""
    metrics = None
    transcript_path_value = session.get("transcript_path")
    if transcript_path_value:
        transcript_text, _, metrics = read_transcript_payload(transcript_path_value)

    return {**session, "transcript": transcript_text, "metrics": metrics}


@app.delete("/sessions/{session_id}")
def delete_transcript_session(session_id: str) -> dict[str, object]:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    deleted_files = 0
    deleted_files += int(delete_file_if_safe(session.get("upload_path"), UPLOADS_DIR))
    deleted_files += int(delete_file_if_safe(session.get("transcript_path"), TRANSCRIPTS_DIR))
    deleted_files += int(delete_file_if_safe(EXPORTS_DIR / f"{session_id}.md", EXPORTS_DIR))

    for snapshot_path in UPLOADS_DIR.glob(f"{session_id}-snapshot-*.webm"):
        deleted_files += int(delete_file_if_safe(snapshot_path, UPLOADS_DIR))

    transcript_dir = TRANSCRIPTS_DIR / session_id
    deleted_transcript_dir = delete_directory_if_safe(transcript_dir, STORAGE_DIR)

    delete_session(session_id)
    return {
        "status": "deleted",
        "session_id": session_id,
        "deleted_files": deleted_files,
        "deleted_transcript_dir": deleted_transcript_dir,
    }


@app.websocket("/transcriptions/live")
async def live_transcription(websocket: WebSocket, language: str = Query(...)) -> None:
    if language not in SUPPORTED_LANGUAGES:
        await websocket.close(code=1008, reason="language must be 'auto', 'zh', or 'id'")
        return

    await websocket.accept()
    session_id = uuid4().hex
    title = "Live transcription"
    transcript_dir = ensure_transcript_dir(session_id)
    live_transcript_path = transcript_dir / "live.json"
    latest_transcript = ""
    snapshot_index = 0
    # Prevent concurrent mlx_whisper calls for the same session.
    # When a chunk is already being transcribed, new chunks are skipped
    # so the WebSocket receive loop never stalls.
    transcription_lock = asyncio.Lock()

    create_session(
        session_id=session_id,
        title=title,
        language=language,
        source="live",
        filename=None,
        upload_path=None,
    )
    await websocket.send_json({"type": "session_started", "session_id": session_id})

    try:
        while True:
            audio_bytes = await websocket.receive_bytes()
            if not audio_bytes:
                continue

            snapshot_index += 1
            snapshot_path = UPLOADS_DIR / f"{session_id}-snapshot-{snapshot_index:04d}.webm"
            async with aiofiles.open(snapshot_path, "wb") as output:
                await output.write(audio_bytes)

            # Skip this chunk if a previous transcription is still running.
            # This keeps the receive loop alive and avoids WebSocket back-pressure.
            if transcription_lock.locked():
                try:
                    await websocket.send_json({"type": "busy"})
                except WebSocketDisconnect:
                    break
                continue

            async with transcription_lock:
                # Use a per-snapshot output subdirectory so JSON files from
                # different snapshots never overwrite or shadow each other.
                snapshot_output_dir = transcript_dir / f"snap-{snapshot_index:04d}"
                try:
                    transcript_text, _ = await asyncio.to_thread(
                        transcribe_with_mlx,
                        snapshot_path,
                        session_id=session_id,
                        language=language,
                        timeout_seconds=120,
                        output_dir_override=snapshot_output_dir,
                    )
                except TranscriptionError as error:
                    try:
                        await websocket.send_json({"type": "error", "message": str(error)})
                    except WebSocketDisconnect:
                        break
                    continue

            if not transcript_text:
                try:
                    await websocket.send_json({"type": "silence"})
                except WebSocketDisconnect:
                    break
                continue

            if transcript_text == latest_transcript:
                try:
                    await websocket.send_json({"type": "unchanged"})
                except WebSocketDisconnect:
                    break
                continue

            latest_transcript = transcript_text
            live_transcript_path.parent.mkdir(parents=True, exist_ok=True)
            live_transcript_path.write_text(
                json.dumps({"text": latest_transcript}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            update_session(session_id, status="processing", transcript_path=live_transcript_path, error=None)
            try:
                await websocket.send_json({"type": "transcript", "text": latest_transcript})
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        final_status = "completed" if latest_transcript else "error"
        final_error = None if latest_transcript else "No speech was transcribed."
        if latest_transcript:
            live_transcript_path.parent.mkdir(parents=True, exist_ok=True)
            live_transcript_path.write_text(
                json.dumps({"text": latest_transcript}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        update_session(
            session_id,
            status=final_status,
            transcript_path=live_transcript_path if latest_transcript else None,
            error=final_error,
        )


@app.post("/transcriptions/upload")
async def upload_transcription(
    file: UploadFile = File(...),
    language: str = Form(...),
) -> dict[str, object]:
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="language must be 'auto', 'zh', or 'id'")

    session_id = uuid4().hex
    safe_filename = Path(file.filename or "audio").name
    upload_path = UPLOADS_DIR / f"{session_id}-{safe_filename}"

    async with aiofiles.open(upload_path, "wb") as output:
        while chunk := await file.read(1024 * 1024):
            await output.write(chunk)

    create_session(
        session_id=session_id,
        title=safe_filename,
        language=language,
        source="upload",
        filename=safe_filename,
        upload_path=upload_path,
    )

    try:
        transcript, transcript_path = await asyncio.to_thread(
            transcribe_with_mlx,
            upload_path,
            session_id=session_id,
            language=language,
        )
    except TranscriptionError as error:
        update_session(session_id, status="error", error=str(error))
        return {
            "session_id": session_id,
            "language": language,
            "status": "error",
            "transcript": "",
            "filename": safe_filename,
            "error": str(error),
        }

    update_session(session_id, status="completed", transcript_path=transcript_path, error=None)
    _, _, metrics = read_transcript_payload(transcript_path)
    return {
        "session_id": session_id,
        "language": language,
        "status": "completed",
        "transcript": transcript,
        "filename": safe_filename,
        "metrics": metrics,
    }


@app.get("/exports/markdown/{session_id}")
def export_markdown(session_id: str) -> FileResponse:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    transcript_path_value = session.get("transcript_path")
    if not transcript_path_value:
        raise HTTPException(status_code=404, detail="Transcript not found")

    transcript_path = Path(str(transcript_path_value))
    if not transcript_path.exists():
        raise HTTPException(status_code=404, detail="Transcript file not found")

    transcript_text, _, metrics = read_transcript_payload(transcript_path)
    markdown = "\n".join(
        [
            f"# {session.get('filename') or 'Trisay Lite Transcript'}",
            "",
            f"- Language: `{session['language']}`",
            f"- Source: `{session['source']}`",
            f"- Created: `{session['created_at']}`",
            *(
                [
                    f"- Processing time: `{float(metrics['processing_seconds']):.1f}s`",
                    f"- Confidence: `{float(metrics['confidence']) * 100:.1f}%`",
                ]
                if metrics
                and isinstance(metrics.get("processing_seconds"), int | float)
                and isinstance(metrics.get("confidence"), int | float)
                else []
            ),
            "",
            "## Transcript",
            "",
            transcript_text,
            "",
        ]
    )

    export_path = EXPORTS_DIR / f"{session_id}.md"
    export_path.write_text(markdown, encoding="utf-8")
    return FileResponse(export_path, media_type="text/markdown", filename=export_path.name)


if FRONTEND_DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST_DIR, html=True), name="frontend")
