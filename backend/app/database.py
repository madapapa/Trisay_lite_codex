import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import DATABASE_PATH, ensure_runtime_dirs


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def get_connection() -> sqlite3.Connection:
    ensure_runtime_dirs()
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                language TEXT NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                filename TEXT,
                upload_path TEXT,
                transcript_path TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def create_session(
    *,
    session_id: str,
    title: str,
    language: str,
    source: str,
    filename: str | None,
    upload_path: Path | None,
) -> None:
    now = utc_now()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO sessions (
                id, title, language, status, source, filename,
                upload_path, transcript_path, error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                title,
                language,
                "processing",
                source,
                filename,
                str(upload_path) if upload_path else None,
                None,
                None,
                now,
                now,
            ),
        )


def update_session(
    session_id: str,
    *,
    status: str,
    transcript_path: Path | None = None,
    error: str | None = None,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE sessions
            SET status = ?, transcript_path = COALESCE(?, transcript_path),
                error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                str(transcript_path) if transcript_path else None,
                error,
                utc_now(),
                session_id,
            ),
        )


def list_sessions() -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, title, language, status, source, filename, created_at, updated_at
            FROM sessions
            ORDER BY created_at DESC
            LIMIT 30
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_session(session_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, title, language, status, source, filename,
                   upload_path, transcript_path, error, created_at, updated_at
            FROM sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_session(session_id: str) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
