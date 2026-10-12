"""Holdout contamination provenance (DR-0004 guard, approved 2026-10-12).

A recording is *contaminated* (permanently ineligible as a holdout reference) when model output for
it could have influenced its reference annotation:
- a transcription is requested while the recording has no finalized annotation (request precedes
  any generation or viewing, so it is the earliest point exposure can happen); or
- a finalized annotation is reopened after a transcription was requested (later edits could be
  informed by the model); or
- its audio is byte-identical to audio that was contaminated before (even if that session was
  deleted); or
- it was transcribed before tracking existed (migration 4 marks it "uncertain").

The fields are write-once (enforced by SQLite triggers) and every relevant action is appended to
`provenance_events`. Changing split or metadata, deleting transcription rows, re-exporting or
restarting the app cannot clear contamination. A recording is eligible as holdout only when
tracking was active and it was never contaminated.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from jamrecall import store

PROVENANCE_VERSION = 1

REASON_REQUEST_BEFORE_FINAL = (
    "transcription requested before the reference annotation was finalized"
)
REASON_REOPEN_AFTER_EXPOSURE = "reference annotation reopened after model output was requested"
REASON_SAME_AUDIO = "audio identical to a previously contaminated recording"


class WouldContaminate(Exception):
    """Raised when an action would disqualify a still-eligible recording and was not confirmed."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def log(conn: sqlite3.Connection, session: dict[str, Any], kind: str, detail: Any = None) -> None:
    conn.execute(
        "INSERT INTO provenance_events (session_id, audio_sha256, kind, at, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            session["id"],
            session["audio_sha256"],
            kind,
            store.now_iso(),
            None if detail is None else json.dumps(detail),
        ),
    )


def _reload(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    return store.get_session(conn, session_id)  # type: ignore[return-value]


def contaminate(conn: sqlite3.Connection, session: dict[str, Any], reason: str) -> None:
    now = store.now_iso()
    if session.get("contaminated_at") is None:
        conn.execute(
            "UPDATE sessions SET contaminated_at = ?, contamination_reason = ? WHERE id = ?",
            (now, reason, session["id"]),
        )
    conn.execute(
        "INSERT OR IGNORE INTO contaminated_audio (audio_sha256, first_at, reason) VALUES (?,?,?)",
        (session["audio_sha256"], now, reason),
    )
    log(conn, session, "contaminated", {"reason": reason})


def _annotation_final(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute(
        "SELECT status FROM annotations WHERE session_id = ?", (session_id,)
    ).fetchone()
    return row is not None and row["status"] == "final"


def on_session_created(conn: sqlite3.Connection, session: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE sessions SET provenance_tracked_since = ? WHERE id = ?",
        (store.now_iso(), session["id"]),
    )
    session = _reload(conn, session["id"])
    log(conn, session, "created")
    prior = conn.execute(
        "SELECT reason FROM contaminated_audio WHERE audio_sha256 = ?", (session["audio_sha256"],)
    ).fetchone()
    if prior is not None:
        contaminate(conn, session, f"{REASON_SAME_AUDIO} ({prior['reason']})")


def would_contaminate_on_transcribe(conn: sqlite3.Connection, session: dict[str, Any]) -> bool:
    return session.get("contaminated_at") is None and not _annotation_final(conn, session["id"])


def on_transcription_requested(
    conn: sqlite3.Connection, session: dict[str, Any], transcription_id: str, confirmed: bool
) -> None:
    """Call before creating the transcription row. Raises WouldContaminate unless confirmed."""
    final = _annotation_final(conn, session["id"])
    disqualifies = session.get("contaminated_at") is None and not final
    if disqualifies and not confirmed:
        raise WouldContaminate(REASON_REQUEST_BEFORE_FINAL)
    if session.get("model_exposed_at") is None:
        conn.execute(
            "UPDATE sessions SET model_exposed_at = ? WHERE id = ?",
            (store.now_iso(), session["id"]),
        )
    log(
        conn,
        session,
        "transcription_requested",
        {
            "transcription_id": transcription_id,
            "annotation_final": final,
            "confirmed_disqualification": bool(disqualifies),
        },
    )
    if disqualifies:
        contaminate(conn, _reload(conn, session["id"]), REASON_REQUEST_BEFORE_FINAL)


def on_model_output_exposed(conn: sqlite3.Connection, session: dict[str, Any], via: str) -> None:
    """Audit trail for every response that carries model notes (API views, exports)."""
    log(
        conn,
        session,
        "model_output_exposed",
        {"via": via, "annotation_final": _annotation_final(conn, session["id"])},
    )


def would_contaminate_on_reopen(session: dict[str, Any]) -> bool:
    return session.get("contaminated_at") is None and session.get("model_exposed_at") is not None


def on_reopen(conn: sqlite3.Connection, session: dict[str, Any], confirmed: bool) -> None:
    disqualifies = would_contaminate_on_reopen(session)
    if disqualifies and not confirmed:
        raise WouldContaminate(REASON_REOPEN_AFTER_EXPOSURE)
    log(conn, session, "annotation_reopened")
    if disqualifies:
        contaminate(conn, session, REASON_REOPEN_AFTER_EXPOSURE)


def on_finalized(conn: sqlite3.Connection, session: dict[str, Any]) -> None:
    log(conn, session, "annotation_finalized")


def status(session: dict[str, Any]) -> dict[str, Any]:
    tracked = session.get("provenance_tracked_since")
    contaminated = session.get("contaminated_at")
    if tracked is None:
        eligible, why = False, "provenance not tracked"
    elif contaminated is not None:
        eligible, why = False, session.get("contamination_reason") or "contaminated"
    else:
        eligible, why = True, None
    return {
        "version": PROVENANCE_VERSION,
        "tracked_since": tracked,
        "model_exposed_at": session.get("model_exposed_at"),
        "contaminated_at": contaminated,
        "contamination_reason": session.get("contamination_reason"),
        "holdout_eligible": eligible,
        "ineligible_reason": why,
    }


def events(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT kind, at, detail FROM provenance_events WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [
        {
            "kind": r["kind"],
            "at": r["at"],
            "detail": json.loads(r["detail"]) if r["detail"] else None,
        }
        for r in rows
    ]
