import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

from .paths import MODEL_DIR, TRANSCRIPTS_DIR

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover - optional dependency fallback
    OpenCC = None


class TranscriptionError(RuntimeError):
    pass


PUNCTUATION_PROMPTS = {
    "auto": "Transcribe each utterance in its original spoken language. Keep English as English and Chinese as Chinese. Use natural punctuation.",
    "zh": "以下是普通话转写文本。请使用自然的中文标点符号，例如：你好，我想咨询一个问题，可以吗？",
    "id": "Transkrip Bahasa Indonesia dengan tanda baca alami. Contoh: Halo, saya ingin bertanya. Apakah bisa?",
}
ZH_SIMPLIFIER = OpenCC("t2s") if OpenCC else None


def is_repetitive_text(text: str) -> bool:
    compact_text = re.sub(r"\s+", "", text)
    if len(compact_text) < 12:
        return False

    for token_size in range(1, 7):
        chunks = [
            compact_text[index : index + token_size]
            for index in range(0, len(compact_text) - token_size + 1, token_size)
        ]
        if len(chunks) < 8:
            continue

        most_common_count = max(chunks.count(chunk) for chunk in set(chunks))
        if most_common_count / len(chunks) >= 0.72:
            return True

    return False


def format_timestamp(seconds: object) -> str:
    try:
        total_seconds = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        total_seconds = 0

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    remaining_seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"


def normalize_transcript_text(text: str, language: str | None) -> str:
    if language in {"auto", "zh"} and ZH_SIMPLIFIER is not None:
        return ZH_SIMPLIFIER.convert(text)
    return text


def clean_transcript_payload(payload: dict[str, object]) -> str:
    language = str(payload.get("requested_language") or payload.get("language") or "")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        return normalize_transcript_text(str(payload.get("text", "")).strip(), language)

    cleaned_parts: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue

        text = str(segment.get("text", "")).strip()
        if not text:
            continue

        compression_ratio = segment.get("compression_ratio")
        if isinstance(compression_ratio, int | float) and compression_ratio > 2.4:
            continue

        if is_repetitive_text(text):
            continue

        text = normalize_transcript_text(text, language)
        cleaned_parts.append(f"[{format_timestamp(segment.get('start'))}] - {text}")

    return "\n".join(cleaned_parts).strip()


def calculate_transcript_metrics(payload: dict[str, object], processing_seconds: float | None = None) -> dict[str, object]:
    segments = payload.get("segments")
    if not isinstance(segments, list):
        return {
            "processing_seconds": processing_seconds,
            "segment_count": 0,
            "kept_segment_count": 0,
            "confidence": None,
            "avg_logprob": None,
            "avg_compression_ratio": None,
            "avg_no_speech_prob": None,
        }

    kept_segments: list[dict[str, object]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text", "")).strip()
        compression_ratio = segment.get("compression_ratio")
        if not text:
            continue
        if isinstance(compression_ratio, int | float) and compression_ratio > 2.4:
            continue
        if is_repetitive_text(text):
            continue
        kept_segments.append(segment)

    def average_number(key: str) -> float | None:
        values = [segment.get(key) for segment in kept_segments]
        numbers = [float(value) for value in values if isinstance(value, int | float)]
        if not numbers:
            return None
        return sum(numbers) / len(numbers)

    avg_logprob = average_number("avg_logprob")
    avg_compression_ratio = average_number("compression_ratio")
    avg_no_speech_prob = average_number("no_speech_prob")
    confidence = None
    if avg_logprob is not None:
        confidence = max(0.0, min(1.0, math.exp(avg_logprob)))

    return {
        "processing_seconds": processing_seconds,
        "segment_count": len(segments),
        "kept_segment_count": len(kept_segments),
        "confidence": confidence,
        "avg_logprob": avg_logprob,
        "avg_compression_ratio": avg_compression_ratio,
        "avg_no_speech_prob": avg_no_speech_prob,
    }


def get_media_duration_seconds(audio_path: Path) -> float | None:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(audio_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None

    try:
        payload = json.loads(result.stdout)
        return float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def default_timeout_seconds(audio_path: Path) -> int:
    duration = get_media_duration_seconds(audio_path)
    if duration is None:
        return 600

    return min(1800, max(300, int(duration * 0.35) + 180))


def transcribe_with_mlx(audio_path: Path, *, session_id: str, language: str, timeout_seconds: int | None = None) -> tuple[str, Path]:
    if not MODEL_DIR.exists():
        raise TranscriptionError(f"Model directory not found: {MODEL_DIR}")

    output_dir = TRANSCRIPTS_DIR / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    effective_timeout_seconds = timeout_seconds or default_timeout_seconds(audio_path)
    started_at = time.perf_counter()

    command = [
        str(Path(sys.executable).parent / "mlx_whisper"),
        str(audio_path),
        "--model",
        str(MODEL_DIR),
        "--output-dir",
        str(output_dir),
        "--output-format",
        "json",
        "--initial-prompt",
        PUNCTUATION_PROMPTS.get(language, ""),
        "--condition-on-previous-text",
        "False",
        "--verbose",
        "False",
    ]
    if language != "auto":
        command[4:4] = ["--language", language]

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=effective_timeout_seconds)
    except subprocess.TimeoutExpired as error:
        raise TranscriptionError(
            f"mlx_whisper timed out after {effective_timeout_seconds} seconds. "
            "Try a shorter audio file or verify MLX/Metal from macOS Terminal."
        ) from error

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "mlx_whisper failed"
        raise TranscriptionError(message)

    json_files = sorted(output_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not json_files:
        raise TranscriptionError("mlx_whisper completed but did not produce a JSON transcript.")

    transcript_path = json_files[0]
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    payload["requested_language"] = language
    text = clean_transcript_payload(payload)
    processing_seconds = time.perf_counter() - started_at
    payload["metrics"] = calculate_transcript_metrics(payload, processing_seconds=processing_seconds)
    payload["text"] = text
    transcript_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return text, transcript_path
