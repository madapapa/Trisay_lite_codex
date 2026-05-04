from __future__ import annotations

import json
import platform
import shutil
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .paths import MODEL_DIR, STORAGE_DIR

MODEL_SETTINGS_PATH = STORAGE_DIR / "model_settings.json"
MODEL_INDEX_URL = "https://huggingface.co/api/models/{repo_id}"
MODEL_FILE_URL = "https://huggingface.co/{repo_id}/resolve/{revision}/{filename}"
DEFAULT_REVISION = "main"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    repo_id: str
    huggingface_url: str
    description: str
    recommended_on_apple_silicon: bool = False


@dataclass
class ModelDownloadJob:
    model_id: str
    status: str
    progress: float
    downloaded_bytes: int
    total_bytes: int
    current_file: str | None
    message: str | None
    started_at: float
    updated_at: float


MODEL_CATALOG: list[ModelSpec] = [
    ModelSpec(
        id="whisper-large-v3-turbo",
        name="Whisper Large V3 Turbo",
        repo_id="mlx-community/whisper-large-v3-turbo",
        huggingface_url="https://huggingface.co/mlx-community/whisper-large-v3-turbo",
        description="Fast MLX build of Whisper large-v3-turbo. Recommended for live transcription on Apple Silicon.",
        recommended_on_apple_silicon=True,
    ),
    ModelSpec(
        id="whisper-large-v3",
        name="Whisper Large V3",
        repo_id="mlx-community/whisper-large-v3-mlx",
        huggingface_url="https://huggingface.co/mlx-community/whisper-large-v3-mlx",
        description="Full Whisper large-v3 in MLX format. Recommended for uploaded media and higher accuracy.",
        recommended_on_apple_silicon=True,
    ),
]

_download_jobs: dict[str, ModelDownloadJob] = {}
_download_lock = threading.Lock()


def _now() -> float:
    return time.time()


def get_machine_info() -> dict[str, Any]:
    machine = platform.machine().lower()
    system = platform.system()
    apple_silicon = system == "Darwin" and machine in {"arm64", "aarch64"}
    return {
        "system": system,
        "machine": machine,
        "apple_silicon": apple_silicon,
        "recommended_family": "mlx" if apple_silicon else "cpu",
    }


def load_model_settings() -> dict[str, str | None]:
    if not MODEL_SETTINGS_PATH.exists():
        return {"selected_model_id": MODEL_CATALOG[0].id}

    try:
        payload = json.loads(MODEL_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"selected_model_id": MODEL_CATALOG[0].id}

    raw_selected_model_id = payload.get("selected_model_id")
    selected_model_id = str(raw_selected_model_id) if raw_selected_model_id else None
    return {"selected_model_id": selected_model_id}


def save_model_settings(selected_model_id: str | None) -> None:
    MODEL_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_SETTINGS_PATH.write_text(
        json.dumps({"selected_model_id": selected_model_id}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_model_spec(model_id: str) -> ModelSpec:
    for spec in MODEL_CATALOG:
        if spec.id == model_id:
            return spec
    raise KeyError(model_id)


def get_model_local_dir(model_id: str) -> Path:
    return MODEL_DIR.parent / model_id


def get_local_model_ids() -> list[str]:
    if not MODEL_DIR.parent.exists():
        return []

    model_ids: list[str] = []
    for path in MODEL_DIR.parent.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        if (path / "config.json").exists():
            model_ids.append(path.name)
    return sorted(set(model_ids))


def is_model_installed(model_id: str) -> bool:
    return (get_model_local_dir(model_id) / "config.json").exists()


def get_selected_model_id() -> str | None:
    settings = load_model_settings()
    selected_model_id = settings.get("selected_model_id")
    if not selected_model_id:
        return None

    if not is_model_installed(selected_model_id):
        return None
    return selected_model_id


def get_active_model_dir() -> Path:
    selected_model_id = get_selected_model_id()
    if not selected_model_id:
        raise FileNotFoundError("No transcription model is started.")
    return get_model_local_dir(selected_model_id)


def list_download_jobs() -> list[dict[str, Any]]:
    with _download_lock:
        return [asdict(job) for job in _download_jobs.values()]


def get_download_job(model_id: str) -> dict[str, Any] | None:
    with _download_lock:
        job = _download_jobs.get(model_id)
        return asdict(job) if job else None


def _set_download_job(job: ModelDownloadJob) -> None:
    with _download_lock:
        _download_jobs[job.model_id] = job


def _update_download_job(model_id: str, **changes: Any) -> None:
    with _download_lock:
        job = _download_jobs[model_id]
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = _now()


def _fetch_model_files(repo_id: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(MODEL_INDEX_URL.format(repo_id=repo_id), headers={"User-Agent": "Trisay-Lite/0.2"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    siblings = payload.get("siblings", [])
    files: list[dict[str, Any]] = []
    for item in siblings:
        if not isinstance(item, dict):
            continue
        filename = item.get("rfilename")
        if not isinstance(filename, str):
            continue
        if filename.startswith(".gitattributes"):
            continue
        if filename.endswith("/"):
            continue
        size = item.get("size")
        files.append({"filename": filename, "size": int(size) if isinstance(size, (int, float)) else None})
    return files


def _download_file(repo_id: str, revision: str, filename: str, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = MODEL_FILE_URL.format(repo_id=repo_id, revision=revision, filename=filename)
    request = urllib.request.Request(url, headers={"User-Agent": "Trisay-Lite/0.2"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        written = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            written += len(chunk)
    return written


def _download_worker(model_id: str) -> None:
    spec = get_model_spec(model_id)
    local_dir = get_model_local_dir(model_id)
    revision = DEFAULT_REVISION
    temp_dir = local_dir.parent / f".{model_id}.downloading"

    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        files = _fetch_model_files(spec.repo_id)
        total_bytes = sum(int(file.get("size") or 0) for file in files)
        _update_download_job(model_id, status="downloading", total_bytes=total_bytes, current_file=None, message=None)

        downloaded_bytes = 0
        for file in files:
            filename = str(file["filename"])
            current_path = temp_dir / filename
            _update_download_job(model_id, current_file=filename)
            downloaded_bytes += _download_file(spec.repo_id, revision, filename, current_path)
            progress = 0.0 if total_bytes <= 0 else min(100.0, (downloaded_bytes / total_bytes) * 100)
            _update_download_job(model_id, downloaded_bytes=downloaded_bytes, progress=progress)

        if local_dir.exists():
            shutil.rmtree(local_dir)
        temp_dir.rename(local_dir)
        _update_download_job(model_id, status="completed", progress=100.0, current_file=None)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        _update_download_job(model_id, status="error", message=str(error))
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def start_model_download(model_id: str) -> dict[str, Any]:
    spec = get_model_spec(model_id)
    if is_model_installed(model_id):
        return {"status": "already_installed", "model_id": model_id}

    existing = get_download_job(model_id)
    if existing and existing.get("status") in {"queued", "downloading"}:
        return existing

    job = ModelDownloadJob(
        model_id=model_id,
        status="queued",
        progress=0.0,
        downloaded_bytes=0,
        total_bytes=0,
        current_file=None,
        message=f"Downloading {spec.name}",
        started_at=_now(),
        updated_at=_now(),
    )
    _set_download_job(job)
    thread = threading.Thread(target=_download_worker, args=(model_id,), daemon=True)
    thread.start()
    return asdict(job)


def delete_model(model_id: str) -> dict[str, Any]:
    local_dir = get_model_local_dir(model_id)
    if local_dir.exists():
        shutil.rmtree(local_dir)

    selected_model_id = get_selected_model_id()
    if selected_model_id == model_id:
        save_model_settings(None)

    with _download_lock:
        _download_jobs.pop(model_id, None)

    return {"status": "deleted", "model_id": model_id}


def select_model(model_id: str) -> dict[str, Any]:
    if not is_model_installed(model_id):
        raise FileNotFoundError(model_id)
    save_model_settings(model_id)
    return {"status": "selected", "model_id": model_id}


def stop_model(model_id: str) -> dict[str, Any]:
    if get_selected_model_id() == model_id:
        save_model_settings(None)
        return {"status": "stopped", "model_id": model_id}
    return {"status": "already_stopped", "model_id": model_id}


def get_model_catalog_state() -> dict[str, Any]:
    selected_model_id = get_selected_model_id()
    machine_info = get_machine_info()
    models: list[dict[str, Any]] = []
    for spec in MODEL_CATALOG:
        local_dir = get_model_local_dir(spec.id)
        models.append(
            {
                **asdict(spec),
                "local_dir": str(local_dir),
                "installed": is_model_installed(spec.id),
                "selected": spec.id == selected_model_id,
                "download_job": get_download_job(spec.id),
                "recommended": machine_info["apple_silicon"] and spec.recommended_on_apple_silicon,
            }
        )
    return {
        "machine": machine_info,
        "selected_model_id": selected_model_id,
        "models": models,
        "downloads": list_download_jobs(),
    }


def get_local_models_state() -> dict[str, Any]:
    selected_model_id = get_selected_model_id()
    local_models: list[dict[str, Any]] = []
    for model_id in get_local_model_ids():
        local_dir = get_model_local_dir(model_id)
        catalog_spec = next((spec for spec in MODEL_CATALOG if spec.id == model_id), None)
        local_models.append(
            {
                "id": model_id,
                "name": catalog_spec.name if catalog_spec else model_id,
                "repo_id": catalog_spec.repo_id if catalog_spec else None,
                "description": catalog_spec.description if catalog_spec else "Imported local model.",
                "local_dir": str(local_dir),
                "installed": True,
                "selected": model_id == selected_model_id,
                "source": "catalog" if catalog_spec else "local",
                "recommended": False,
            }
        )

    return {
        "selected_model_id": selected_model_id,
        "models": local_models,
    }


def import_local_model(model_id: str, files: list[tuple[str, bytes]]) -> dict[str, Any]:
    safe_model_id = model_id.strip().replace("/", "-")
    if not safe_model_id:
        raise ValueError("model_id is required")

    destination = get_model_local_dir(safe_model_id)
    staging_dir = destination.parent / f".{safe_model_id}.importing"

    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    if destination.exists():
        shutil.rmtree(destination)

    for relative_path, content in files:
        rel_path = Path(relative_path)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ValueError(f"invalid relative path: {relative_path}")
        target = staging_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    if not (staging_dir / "config.json").exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise ValueError("config.json not found in imported directory")

    staging_dir.rename(destination)

    if get_selected_model_id() == safe_model_id:
        save_model_settings(safe_model_id)

    return {"status": "imported", "model_id": safe_model_id}
