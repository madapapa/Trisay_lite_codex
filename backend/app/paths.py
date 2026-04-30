from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = PROJECT_ROOT / "models" / "whisper-large-v3-turbo"
STORAGE_DIR = PROJECT_ROOT / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
TRANSCRIPTS_DIR = STORAGE_DIR / "transcripts"
EXPORTS_DIR = STORAGE_DIR / "exports"
DATABASE_PATH = STORAGE_DIR / "trisay_lite.sqlite3"


def ensure_runtime_dirs() -> None:
    for directory in (UPLOADS_DIR, TRANSCRIPTS_DIR, EXPORTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
