"""Reference annotations: human-made ground-truth notes, stored separately from model output.

A session has at most one annotation. Transcription runs (`note_events`) are never modified; an
annotation may be *seeded* from one, and the seed is recorded as provenance because a reference
seeded from an engine's output is not independent evidence for that engine
(docs/research/real-recording-validation-protocol.md). Once finalized, the dev/holdout split is
locked for good; reopening an annotation increments its revision.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any

from jamrecall import store

TECHNIQUES = ("bend", "slide", "hammer_on", "pull_off", "vibrato", "harmonic", "palm_mute", "other")
MAX_NOTES = 5000
REFERENCE_FORMAT = "jamrecall-reference-v1"


class AnnotationError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def validate_notes(notes: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    if len(notes) > MAX_NOTES:
        raise AnnotationError(422, "too_many_notes", f"At most {MAX_NOTES} notes")
    out = []
    for i, n in enumerate(notes):
        start, end, midi = n["start_seconds"], n["end_seconds"], n["midi_pitch"]
        if not (math.isfinite(start) and math.isfinite(end)):
            raise AnnotationError(422, "invalid_note", f"Note {i + 1}: times must be numbers")
        # Validate the values that will be stored (4-decimal rounding).
        start, end = round(float(start), 4), round(float(end), 4)
        if start < 0 or end <= start:
            raise AnnotationError(422, "invalid_note", f"Note {i + 1}: end must be after start ≥ 0")
        if end > duration + 1e-6:
            raise AnnotationError(
                422, "invalid_note", f"Note {i + 1}: ends after the recording ({duration:.3f} s)"
            )
        if not 0 <= midi <= 127:
            raise AnnotationError(422, "invalid_note", f"Note {i + 1}: MIDI pitch must be 0-127")
        tech = n.get("technique") or None
        if tech is not None and tech not in TECHNIQUES:
            raise AnnotationError(422, "invalid_note", f"Note {i + 1}: unknown technique '{tech}'")
        out.append(
            {
                "start_seconds": round(float(start), 4),
                "end_seconds": round(min(float(end), duration), 4),
                "midi_pitch": int(midi),
                "technique": tech,
            }
        )
    out.sort(key=lambda n: (n["start_seconds"], n["midi_pitch"]))
    for a, b in zip(out, out[1:], strict=False):
        if b["start_seconds"] < a["end_seconds"] - 1e-9:
            raise AnnotationError(
                422,
                "notes_overlap",
                f"Notes at {a['start_seconds']:.3f} s and {b['start_seconds']:.3f} s overlap; "
                "reference notes must be monophonic",
            )
    return out


def get(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM annotations WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    a = dict(row)
    a["notes"] = [
        dict(r)
        for r in conn.execute(
            """SELECT start_seconds, end_seconds, midi_pitch, technique FROM annotation_notes
               WHERE annotation_id = ? ORDER BY start_seconds, midi_pitch""",
            (a["id"],),
        ).fetchall()
    ]
    a["split_locked"] = bool(a["split_locked"])
    return a


def resolve_seed(conn: sqlite3.Connection, session_id: str, seed: str) -> str:
    if seed == "blank":
        return "blank"
    if seed.startswith("transcription:"):
        tid = seed.split(":", 1)[1]
        t = store.get_transcription(conn, tid)
        if t is None or t["session_id"] != session_id:
            raise AnnotationError(422, "invalid_seed", "Seed transcription not found for session")
        return f"transcription:{tid}:{t['engine']}@{t['engine_version']}"
    raise AnnotationError(422, "invalid_seed", "seed must be 'blank' or 'transcription:<id>'")


def save(conn: sqlite3.Connection, session: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    existing = get(conn, session["id"])
    notes = validate_notes(body["notes"], session["duration_seconds"])
    now = store.now_iso()
    fields = {
        k: body.get(k) for k in ("split", "condition", "annotator", "instrument", "notes_text")
    }
    fields["method"] = body.get("method") or "manual"
    if existing is None:
        aid = store.new_id()
        conn.execute(
            """INSERT INTO annotations (id, session_id, status, split, condition, method, seed,
                   annotator, instrument, notes_text, created_at, updated_at)
               VALUES (:id, :sid, 'draft', :split, :condition, :method, :seed, :annotator,
                   :instrument, :notes_text, :now, :now)""",
            fields
            | {
                "id": aid,
                "sid": session["id"],
                "now": now,
                "seed": resolve_seed(conn, session["id"], body.get("seed") or "blank"),
            },
        )
    else:
        aid = existing["id"]
        if existing["status"] == "final":
            raise AnnotationError(409, "annotation_final", "Reopen the annotation to edit it")
        if existing["split_locked"] and fields["split"] != existing["split"]:
            raise AnnotationError(
                409,
                "split_locked",
                "This recording was already finalized as "
                f"'{existing['split']}'; its split can no longer change",
            )
        conn.execute(
            """UPDATE annotations SET split = :split, condition = :condition, method = :method,
                   annotator = :annotator, instrument = :instrument, notes_text = :notes_text,
                   updated_at = :now WHERE id = :id""",
            fields | {"id": aid, "now": now},
        )
        conn.execute("DELETE FROM annotation_notes WHERE annotation_id = ?", (aid,))
    conn.executemany(
        """INSERT INTO annotation_notes (annotation_id, start_seconds, end_seconds, midi_pitch,
               technique) VALUES (?, ?, ?, ?, ?)""",
        [
            (aid, n["start_seconds"], n["end_seconds"], n["midi_pitch"], n["technique"])
            for n in notes
        ],
    )
    return get(conn, session["id"])  # type: ignore[return-value]


def finalize(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    a = get(conn, session_id)
    if a is None:
        raise AnnotationError(404, "no_annotation", "This session has no annotation")
    missing = [k for k in ("split", "condition", "annotator") if not a.get(k)]
    if missing:
        raise AnnotationError(422, "incomplete_annotation", f"Set {', '.join(missing)} first")
    if not a["notes"]:
        raise AnnotationError(422, "incomplete_annotation", "Add at least one note")
    conn.execute(
        """UPDATE annotations SET status = 'final', split_locked = 1, finalized_at = ?,
               updated_at = ? WHERE id = ?""",
        (store.now_iso(), store.now_iso(), a["id"]),
    )
    return get(conn, session_id)  # type: ignore[return-value]


def reopen(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    a = get(conn, session_id)
    if a is None:
        raise AnnotationError(404, "no_annotation", "This session has no annotation")
    conn.execute(
        """UPDATE annotations SET status = 'draft', revision = revision + 1, updated_at = ?
           WHERE id = ?""",
        (store.now_iso(), a["id"]),
    )
    return get(conn, session_id)  # type: ignore[return-value]


def reference_document(session: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
    """Protocol reference format (bench/jamrecall_bench/real.py reads it)."""
    return {
        "format": REFERENCE_FORMAT,
        "session_id": session["id"],
        "audio_sha256": session["audio_sha256"],
        "duration_seconds": session["duration_seconds"],
        "status": a["status"],
        "revision": a["revision"],
        "split": a["split"],
        "condition": a["condition"],
        "method": a["method"],
        "seed": a["seed"],
        "annotator": a["annotator"],
        "instrument": a["instrument"],
        "notes_text": a["notes_text"],
        "created_at": a["created_at"],
        "finalized_at": a["finalized_at"],
        "notes": [
            {
                "start": n["start_seconds"],
                "end": n["end_seconds"],
                "midi": n["midi_pitch"],
                "technique": n["technique"],
            }
            for n in a["notes"]
        ],
    }
