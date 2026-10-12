"""Row-level persistence helpers. All functions take an open sqlite3 connection."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from jamrecall.fingering import Fingering
from jamrecall.transcription.base import DetectedNote


def new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


# --- sessions ---------------------------------------------------------------------------------


def insert_session(conn: sqlite3.Connection, **fields: Any) -> dict[str, Any]:
    conn.execute(
        """INSERT INTO sessions (id, audio_path, audio_mime, audio_bytes, audio_sha256,
               duration_seconds, sample_rate, created_at, capture_info)
           VALUES (:id, :audio_path, :audio_mime, :audio_bytes, :audio_sha256,
               :duration_seconds, :sample_rate, :created_at, :capture_info)""",
        {"capture_info": None} | fields,
    )
    return get_session(conn, fields["id"])  # type: ignore[return-value]


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())


def list_sessions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT s.*, (SELECT COUNT(*) FROM riffs r WHERE r.session_id = s.id) AS riff_count
           FROM sessions s ORDER BY s.created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


# --- transcriptions ---------------------------------------------------------------------------


def insert_transcription(
    conn: sqlite3.Connection, session_id: str, engine: str, version: str, test_only: bool
) -> dict[str, Any]:
    tid = new_id()
    conn.execute(
        """INSERT INTO transcriptions (id, session_id, engine, engine_version, test_only, status,
               created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
        (tid, session_id, engine, version, int(test_only), now_iso()),
    )
    return get_transcription(conn, tid)  # type: ignore[return-value]


def get_transcription(conn: sqlite3.Connection, tid: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM transcriptions WHERE id = ?", (tid,)).fetchone())


def latest_transcription(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            """SELECT * FROM transcriptions WHERE session_id = ?
               ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
    )


def list_transcriptions(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM transcriptions WHERE session_id = ? ORDER BY created_at DESC, rowid DESC",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_transcription(conn: sqlite3.Connection, tid: str, status: str, **fields: Any) -> None:
    sets = ["status = :status"] + [f"{k} = :{k}" for k in fields]
    conn.execute(
        f"UPDATE transcriptions SET {', '.join(sets)} WHERE id = :id",
        {"status": status, "id": tid, **fields},
    )


def insert_notes(
    conn: sqlite3.Connection, tid: str, notes: list[DetectedNote], fingerings: list[Fingering]
) -> None:
    conn.executemany(
        """INSERT INTO note_events (transcription_id, start_seconds, end_seconds, midi_pitch,
               confidence, string, fret, fingering_alternatives) VALUES (?,?,?,?,?,?,?,?)""",
        [
            (
                tid,
                n.start_seconds,
                n.end_seconds,
                n.midi_pitch,
                n.confidence,
                f.position.string if f.position else None,
                f.position.fret if f.position else None,
                f.alternatives,
            )
            for n, f in zip(notes, fingerings, strict=True)
        ],
    )


def list_notes(conn: sqlite3.Connection, tid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM note_events WHERE transcription_id = ? ORDER BY start_seconds, midi_pitch",
        (tid,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- riffs ------------------------------------------------------------------------------------


def insert_riff(
    conn: sqlite3.Connection, session_id: str, title: str, start: float, end: float
) -> dict[str, Any]:
    rid = new_id()
    conn.execute(
        """INSERT INTO riffs (id, session_id, title, start_seconds, end_seconds, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (rid, session_id, title, start, end, now_iso()),
    )
    return get_riff(conn, rid)  # type: ignore[return-value]


def get_riff(conn: sqlite3.Connection, rid: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM riffs WHERE id = ?", (rid,)).fetchone())


def list_riffs(conn: sqlite3.Connection, session_id: str | None = None) -> list[dict[str, Any]]:
    if session_id is None:
        rows = conn.execute("SELECT * FROM riffs ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM riffs WHERE session_id = ? ORDER BY start_seconds, created_at",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_riff(conn: sqlite3.Connection, rid: str) -> bool:
    return conn.execute("DELETE FROM riffs WHERE id = ?", (rid,)).rowcount > 0
