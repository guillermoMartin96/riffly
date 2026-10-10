"""Export and deletion of a session's data (used by the API and `python -m jamrecall.manage`)."""

from __future__ import annotations

import io
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

from jamrecall import annotations, store
from jamrecall.config import Settings

EXPORT_FORMAT = "jamrecall-export-v1"


def session_dict(session: dict[str, Any]) -> dict[str, Any]:
    out = dict(session)
    out.pop("riff_count", None)
    raw = out.pop("capture_info", None)
    out["capture_info"] = json.loads(raw) if raw else None
    return out


def transcriptions_document(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    runs = []
    for t in store.list_transcriptions(conn, session_id):
        notes = store.list_notes(conn, t["id"])
        runs.append(
            t
            | {
                "test_only": bool(t["test_only"]),
                "notes": [
                    {
                        k: n[k]
                        for k in (
                            "start_seconds",
                            "end_seconds",
                            "midi_pitch",
                            "confidence",
                            "string",
                            "fret",
                            "fingering_alternatives",
                        )
                    }
                    for n in notes
                ],
            }
        )
    return runs


def export_zip(settings: Settings, conn: sqlite3.Connection, session_id: str) -> bytes:
    session = store.get_session(conn, session_id)
    if session is None:
        raise KeyError(session_id)
    audio = settings.data_dir / session["audio_path"]
    ann = annotations.get(conn, session_id)
    metadata = {
        "format": EXPORT_FORMAT,
        "exported_at": store.now_iso(),
        "session": session_dict(session),
        "audio_file": f"audio/{audio.name}" if audio.is_file() else None,
        "audio_missing": not audio.is_file(),
        "riffs": store.list_riffs(conn, session_id),
        "annotation_status": ann["status"] if ann else None,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if audio.is_file():
            z.write(audio, f"audio/{audio.name}")  # original bytes, unmodified
        z.writestr("metadata.json", json.dumps(metadata, indent=1))
        z.writestr(
            "transcriptions.json", json.dumps(transcriptions_document(conn, session_id), indent=1)
        )
        if ann is not None:
            z.writestr(
                "reference.json", json.dumps(annotations.reference_document(session, ann), indent=1)
            )
        z.writestr(
            "README.txt",
            (
                "JamRecall session export.\n"
                "audio/               original recording, byte-for-byte as uploaded\n"
                "                     (sha256 in metadata.json)\n"
                "reference.json       human reference annotation (if any), kept separate\n"
                "                     from model output\n"
                "transcriptions.json  every transcription run with engine/version and notes\n"
                "metadata.json        session, capture settings, riffs\n"
                "Times are seconds on the original recording's clock;\n"
                "note intervals are [start, end).\n"
            ),
        )
    return buf.getvalue()


def delete_session(settings: Settings, conn: sqlite3.Connection, session_id: str) -> bool:
    """Permanently delete a session: rows in every table and its media directory."""
    session = store.get_session(conn, session_id)
    if session is None:
        return False
    conn.execute(
        "DELETE FROM annotation_notes WHERE annotation_id IN "
        "(SELECT id FROM annotations WHERE session_id = ?)",
        (session_id,),
    )
    conn.execute("DELETE FROM annotations WHERE session_id = ?", (session_id,))
    conn.execute(
        "DELETE FROM note_events WHERE transcription_id IN "
        "(SELECT id FROM transcriptions WHERE session_id = ?)",
        (session_id,),
    )
    conn.execute("DELETE FROM transcriptions WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM riffs WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    media = (settings.data_dir / session["audio_path"]).parent
    if media.is_dir() and media.parent == settings.media_dir / "sessions":
        shutil.rmtree(media)
    return True


def wipe(settings: Settings) -> Path:
    """Delete the whole data directory (database and all recordings)."""
    if settings.data_dir.exists():
        shutil.rmtree(settings.data_dir)
    return settings.data_dir
