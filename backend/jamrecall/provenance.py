"""Holdout contamination provenance (DR-0004 guard, approved 2026-10-12).

A recording is *contaminated* (permanently ineligible as a holdout reference) when model output for
it could have influenced its reference annotation:
- a transcription is requested while the recording has no finalized annotation (request precedes
  any generation or viewing, so it is the earliest point exposure can happen); or
- a finalized annotation is reopened after a transcription was requested (later edits could be
  informed by the model); or
- its audio (container bytes or decoded samples) was uploaded before, in any session, even a
  deleted one: a re-upload is never an independent take (`seen_audio`); or
- it was transcribed before tracking existed (migration 4 marks it "uncertain").

Additionally only recordings made with the in-app recorder and tracked from creation
(`provenance_origin = 'recorded'`) can be eligible; imported files and recordings that predate
tracking cannot. SQLite triggers (migration 5) enforce the ordering invariants: a transcription row
cannot be inserted before exposure (and, if unfinalized, contamination) is recorded, and an exposed
finalized reference cannot be reopened before contamination is recorded. All checks run inside
BEGIN IMMEDIATE transactions with freshly read state.

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
REASON_DUPLICATE = "duplicate of audio uploaded before"
RECORDER_MIMES = ("audio/webm", "audio/ogg", "audio/mp4")


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
    for h in {session["audio_sha256"], session.get("pcm_sha256")} - {None}:
        # Both identities: the container hash and the decoded-audio hash.
        conn.execute(
            "INSERT OR IGNORE INTO contaminated_audio (audio_sha256, first_at, reason) "
            "VALUES (?,?,?)",
            (h, now, reason),
        )
    log(conn, session, "contaminated", {"reason": reason})


def audio_group(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    """The session plus every other session with the same audio (container or decoded hash).
    Model output for one of them is model output for all of them."""
    s = _reload(conn, session_id)
    rows = conn.execute(
        "SELECT id FROM sessions WHERE id != ? AND (audio_sha256 = ? "
        "OR (? IS NOT NULL AND pcm_sha256 = ?))",
        (s["id"], s["audio_sha256"], s.get("pcm_sha256"), s.get("pcm_sha256")),
    ).fetchall()
    return [s] + [_reload(conn, r[0]) for r in rows]


def _expose_group(
    conn: sqlite3.Connection, session_id: str, event: str, confirmed: bool, detail: dict
) -> None:
    """Record model-output exposure for a session and every session sharing its audio.

    Any member that is still uncontaminated and has no finalized reference becomes contaminated;
    unless `confirmed`, that raises WouldContaminate first (nothing is written).
    """
    group = audio_group(conn, session_id)
    victims = [
        m
        for m in group
        if m.get("contaminated_at") is None and not _annotation_final(conn, m["id"])
    ]
    if victims and not confirmed:
        raise WouldContaminate(REASON_REQUEST_BEFORE_FINAL)
    now = store.now_iso()
    for m in group:
        if m.get("model_exposed_at") is None:
            conn.execute("UPDATE sessions SET model_exposed_at = ? WHERE id = ?", (now, m["id"]))
        log(
            conn,
            m,
            event,
            detail
            | {
                "via_session": session_id,
                "annotation_final": _annotation_final(conn, m["id"]),
                "confirmed_disqualification": any(v["id"] == m["id"] for v in victims),
            },
        )
    for v in victims:
        reason = (
            REASON_REQUEST_BEFORE_FINAL
            if v["id"] == session_id
            else (f"{REASON_REQUEST_BEFORE_FINAL} (identical audio in session {session_id})")
        )
        contaminate(conn, _reload(conn, v["id"]), reason)


def _annotation_final(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute(
        "SELECT status FROM annotations WHERE session_id = ?", (session_id,)
    ).fetchone()
    return row is not None and row["status"] == "final"


def on_session_created(
    conn: sqlite3.Connection, session: dict[str, Any], pcm_sha256: str, recorded: bool
) -> None:
    """Start tracking at creation. `recorded`: captured by the in-app recorder (browser path)."""
    origin = "recorded" if recorded and session["audio_mime"] in RECORDER_MIMES else "imported"
    conn.execute(
        "UPDATE sessions SET provenance_tracked_since = ?, provenance_origin = ?, pcm_sha256 = ? "
        "WHERE id = ?",
        (store.now_iso(), origin, pcm_sha256, session["id"]),
    )
    session = _reload(conn, session["id"])
    log(conn, session, "created", {"origin": origin, "pcm_sha256": pcm_sha256})
    seen = conn.execute(
        "SELECT first_session_id, kind FROM seen_audio WHERE hash IN (?, ?)",
        (session["audio_sha256"], pcm_sha256),
    ).fetchone()
    prior = conn.execute(
        "SELECT reason FROM contaminated_audio WHERE audio_sha256 = ?", (session["audio_sha256"],)
    ).fetchone()
    if prior is not None:
        contaminate(conn, session, f"{REASON_SAME_AUDIO} ({prior['reason']})")
    elif seen is not None:
        contaminate(conn, session, f"{REASON_DUPLICATE} (session {seen['first_session_id']})")
    for h, kind in ((session["audio_sha256"], "container"), (pcm_sha256, "pcm")):
        conn.execute(
            "INSERT OR IGNORE INTO seen_audio (hash, kind, first_session_id, first_at) "
            "VALUES (?, ?, ?, ?)",
            (h, kind, session["id"], store.now_iso()),
        )


def would_contaminate_on_transcribe(conn: sqlite3.Connection, session: dict[str, Any]) -> bool:
    return session.get("contaminated_at") is None and not _annotation_final(conn, session["id"])


def on_transcription_requested(conn: sqlite3.Connection, session_id: str, confirmed: bool) -> None:
    """Call BEFORE inserting the transcription row (a trigger enforces this ordering).

    Exposure covers every session with the same audio. Raises WouldContaminate if any of them is
    still eligible without a finalized reference and the disqualification was not confirmed.
    """
    _expose_group(conn, session_id, "transcription_requested", confirmed, {})


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


def on_reopen(conn: sqlite3.Connection, session_id: str, confirmed: bool) -> None:
    """Call BEFORE reopening (a trigger enforces this ordering)."""
    session = _reload(conn, session_id)  # fresh state inside the serialized transaction
    disqualifies = would_contaminate_on_reopen(session)
    if disqualifies and not confirmed:
        raise WouldContaminate(REASON_REOPEN_AFTER_EXPOSURE)
    log(conn, session, "annotation_reopened")
    if disqualifies:
        contaminate(conn, session, REASON_REOPEN_AFTER_EXPOSURE)


def on_finalized(conn: sqlite3.Connection, session: dict[str, Any]) -> None:
    log(conn, session, "annotation_finalized")


def baseline_complete(conn: sqlite3.Connection) -> bool:
    """True only if this database was created with full contamination tracking (migration 6)."""
    try:
        row = conn.execute("SELECT status FROM provenance_baseline WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None and row[0] == "complete"


def on_validation_output(conn: sqlite3.Connection, session_id: str) -> None:
    """The validation gate is about to produce model output for this finalized recording: record
    the exposure first (for every session sharing its audio), so later reopening contaminates.
    A deliberate validation run counts as confirmation for unfinalized identical copies."""
    _expose_group(conn, session_id, "validation_output_produced", True, {})


def status(session: dict[str, Any], baseline_ok: bool = False) -> dict[str, Any]:
    """Holdout eligibility. `baseline_ok` must come from `baseline_complete(conn)`: in a database
    with history from before full tracking nothing is eligible (fail closed by default)."""
    tracked = session.get("provenance_tracked_since")
    contaminated = session.get("contaminated_at")
    origin = session.get("provenance_origin")
    if not baseline_ok:
        eligible, why = False, "data directory existed before full contamination tracking"
    elif tracked is None or origin is None or origin == "pre-tracking":
        eligible, why = False, "provenance not tracked from creation"
    elif contaminated is not None:
        eligible, why = False, session.get("contamination_reason") or "contaminated"
    elif origin != "recorded":
        eligible, why = False, "not recorded with the in-app recorder"
    else:
        eligible, why = True, None
    return {
        "version": PROVENANCE_VERSION,
        "tracked_since": tracked,
        "origin": origin,
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
