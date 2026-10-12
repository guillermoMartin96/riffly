"""SQLite persistence: connection helper and versioned schema migrations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: initial M1 schema
    """
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        audio_path TEXT NOT NULL,
        audio_mime TEXT NOT NULL,
        audio_bytes INTEGER NOT NULL CHECK (audio_bytes > 0),
        audio_sha256 TEXT NOT NULL,
        duration_seconds REAL NOT NULL CHECK (duration_seconds > 0),
        sample_rate INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE transcriptions (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id),
        engine TEXT NOT NULL,
        engine_version TEXT NOT NULL,
        test_only INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL CHECK (status IN ('pending','running','succeeded','failed')),
        error TEXT,
        fingering_method TEXT,
        processing_seconds REAL,
        created_at TEXT NOT NULL,
        completed_at TEXT
    );
    CREATE INDEX transcriptions_session ON transcriptions(session_id, created_at);
    CREATE TABLE note_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transcription_id TEXT NOT NULL REFERENCES transcriptions(id),
        start_seconds REAL NOT NULL CHECK (start_seconds >= 0),
        end_seconds REAL NOT NULL CHECK (end_seconds > start_seconds),
        midi_pitch INTEGER NOT NULL CHECK (midi_pitch BETWEEN 0 AND 127),
        confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
        string INTEGER CHECK (string IS NULL OR string BETWEEN 1 AND 6),
        fret INTEGER CHECK (fret IS NULL OR fret >= 0),
        fingering_alternatives INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX note_events_transcription ON note_events(transcription_id, start_seconds);
    CREATE TABLE riffs (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id),
        title TEXT NOT NULL CHECK (length(title) > 0),
        start_seconds REAL NOT NULL CHECK (start_seconds >= 0),
        end_seconds REAL NOT NULL CHECK (end_seconds > start_seconds),
        created_at TEXT NOT NULL
    );
    CREATE INDEX riffs_session ON riffs(session_id, start_seconds);
    """,
    # 2: stage timings for latency profiling
    """
    ALTER TABLE transcriptions ADD COLUMN decode_seconds REAL;
    ALTER TABLE transcriptions ADD COLUMN inference_seconds REAL;
    """,
    # 3: capture metadata; reference annotations kept separate from model output (DR-0003)
    """
    ALTER TABLE sessions ADD COLUMN capture_info TEXT;
    CREATE TABLE annotations (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),
        status TEXT NOT NULL CHECK (status IN ('draft','final')),
        split TEXT CHECK (split IS NULL OR split IN ('dev','holdout')),
        condition TEXT CHECK (condition IS NULL OR condition IN ('A','B','C','D')),
        method TEXT NOT NULL CHECK (method IN ('manual','score')),
        seed TEXT NOT NULL,
        annotator TEXT,
        instrument TEXT,
        notes_text TEXT,
        split_locked INTEGER NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        finalized_at TEXT
    );
    CREATE TABLE annotation_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        annotation_id TEXT NOT NULL REFERENCES annotations(id),
        start_seconds REAL NOT NULL CHECK (start_seconds >= 0),
        end_seconds REAL NOT NULL CHECK (end_seconds > start_seconds),
        midi_pitch INTEGER NOT NULL CHECK (midi_pitch BETWEEN 0 AND 127),
        technique TEXT
    );
    CREATE INDEX annotation_notes_annotation ON annotation_notes(annotation_id, start_seconds);
    """,
    # 4: holdout contamination provenance (DR-0004 guard). Write-once fields + append-only log.
    """
    ALTER TABLE sessions ADD COLUMN provenance_tracked_since TEXT;
    ALTER TABLE sessions ADD COLUMN model_exposed_at TEXT;
    ALTER TABLE sessions ADD COLUMN contaminated_at TEXT;
    ALTER TABLE sessions ADD COLUMN contamination_reason TEXT;
    CREATE TABLE provenance_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        audio_sha256 TEXT NOT NULL,
        kind TEXT NOT NULL,
        at TEXT NOT NULL,
        detail TEXT
    );
    CREATE INDEX provenance_events_session ON provenance_events(session_id, id);
    -- Survives deletion of the session: identical audio re-uploaded later stays contaminated.
    CREATE TABLE contaminated_audio (
        audio_sha256 TEXT PRIMARY KEY,
        first_at TEXT NOT NULL,
        reason TEXT NOT NULL
    );
    -- Backfill: recordings transcribed before tracking existed have uncertain provenance.
    UPDATE sessions SET provenance_tracked_since = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
    UPDATE sessions
       SET model_exposed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
           contaminated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
           contamination_reason = 'uncertain: transcribed before contamination tracking existed'
     WHERE EXISTS (SELECT 1 FROM transcriptions t WHERE t.session_id = sessions.id);
    INSERT OR IGNORE INTO contaminated_audio
        SELECT audio_sha256, contaminated_at, contamination_reason FROM sessions
         WHERE contaminated_at IS NOT NULL;
    -- Irreversibility: once set, exposure/contamination cannot be cleared or rewritten.
    CREATE TRIGGER sessions_contamination_write_once BEFORE UPDATE ON sessions
    WHEN (OLD.contaminated_at IS NOT NULL
          AND (NEW.contaminated_at IS NULL OR NEW.contaminated_at != OLD.contaminated_at
               OR NEW.contamination_reason IS NOT OLD.contamination_reason))
      OR (OLD.model_exposed_at IS NOT NULL
          AND (NEW.model_exposed_at IS NULL OR NEW.model_exposed_at != OLD.model_exposed_at))
      OR (OLD.provenance_tracked_since IS NOT NULL
          AND NEW.provenance_tracked_since IS NOT OLD.provenance_tracked_since)
    BEGIN
        SELECT RAISE(ABORT, 'provenance is write-once');
    END;
    CREATE TRIGGER provenance_events_no_update BEFORE UPDATE ON provenance_events
    BEGIN
        SELECT RAISE(ABORT, 'provenance events are append-only');
    END;
    CREATE TRIGGER provenance_events_no_delete BEFORE DELETE ON provenance_events
    WHEN EXISTS (SELECT 1 FROM sessions WHERE id = OLD.session_id)
    BEGIN
        SELECT RAISE(ABORT, 'provenance events are append-only');
    END;
    CREATE TRIGGER contaminated_audio_no_update BEFORE UPDATE ON contaminated_audio
    BEGIN
        SELECT RAISE(ABORT, 'contaminated audio records are permanent');
    END;
    CREATE TRIGGER contaminated_audio_no_delete BEFORE DELETE ON contaminated_audio
    BEGIN
        SELECT RAISE(ABORT, 'contaminated audio records are permanent');
    END;
    """,
    # 5: contamination guard hardening (Codex review of the guard, 2026-10-12)
    """
    -- How the recording entered: 'recorded' (in-app recorder, tracked from creation),
    -- 'imported' (any other upload), 'pre-tracking' (existed before migration 4). Only
    -- 'recorded' can be holdout-eligible. Decoded-audio hash catches container re-wraps.
    ALTER TABLE sessions ADD COLUMN provenance_origin TEXT;
    ALTER TABLE sessions ADD COLUMN pcm_sha256 TEXT;
    UPDATE sessions SET provenance_origin = CASE
        WHEN EXISTS (SELECT 1 FROM provenance_events e
                     WHERE e.session_id = sessions.id AND e.kind = 'created')
             AND capture_info IS NOT NULL AND audio_mime IN ('audio/webm','audio/ogg','audio/mp4')
        THEN 'recorded'
        WHEN EXISTS (SELECT 1 FROM provenance_events e
                     WHERE e.session_id = sessions.id AND e.kind = 'created')
        THEN 'imported'
        ELSE 'pre-tracking' END;
    -- Every audio identity ever uploaded (container hash and decoded-audio hash). Permanent:
    -- a later upload of the same audio is never an independent take.
    CREATE TABLE seen_audio (
        hash TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        first_session_id TEXT NOT NULL,
        first_at TEXT NOT NULL
    );
    INSERT OR IGNORE INTO seen_audio
        SELECT audio_sha256, 'container', id, created_at FROM sessions;
    CREATE TRIGGER seen_audio_no_update BEFORE UPDATE ON seen_audio
    BEGIN SELECT RAISE(ABORT, 'seen audio records are permanent'); END;
    CREATE TRIGGER seen_audio_no_delete BEFORE DELETE ON seen_audio
    BEGIN SELECT RAISE(ABORT, 'seen audio records are permanent'); END;
    CREATE TRIGGER sessions_origin_write_once BEFORE UPDATE ON sessions
    WHEN (OLD.provenance_origin IS NOT NULL
          AND NEW.provenance_origin IS NOT OLD.provenance_origin)
      OR (OLD.pcm_sha256 IS NOT NULL AND NEW.pcm_sha256 IS NOT OLD.pcm_sha256)
    BEGIN SELECT RAISE(ABORT, 'provenance is write-once'); END;
    -- Invariant: a transcription row can only exist once exposure is recorded, and, if the
    -- reference is not finalized, once the recording is marked contaminated.
    CREATE TRIGGER transcriptions_require_provenance BEFORE INSERT ON transcriptions
    WHEN (SELECT model_exposed_at FROM sessions WHERE id = NEW.session_id) IS NULL
      OR (NOT EXISTS (SELECT 1 FROM annotations a
                      WHERE a.session_id = NEW.session_id AND a.status = 'final')
          AND (SELECT contaminated_at FROM sessions WHERE id = NEW.session_id) IS NULL)
    BEGIN SELECT RAISE(ABORT, 'record exposure/contamination before creating a transcription'); END;
    -- Invariant: a finalized reference can only be reopened after exposure if contamination
    -- has been recorded.
    CREATE TRIGGER annotations_reopen_requires_contamination BEFORE UPDATE OF status ON annotations
    WHEN OLD.status = 'final' AND NEW.status != 'final'
      AND (SELECT model_exposed_at FROM sessions WHERE id = OLD.session_id) IS NOT NULL
      AND (SELECT contaminated_at FROM sessions WHERE id = OLD.session_id) IS NULL
    BEGIN SELECT RAISE(ABORT, 'record contamination before reopening an exposed reference'); END;
    -- Invariant: a finalized reference cannot change without reopening it first.
    CREATE TRIGGER annotations_final_immutable BEFORE UPDATE ON annotations
    WHEN OLD.status = 'final' AND NEW.status = 'final'
      AND (NEW.split IS NOT OLD.split OR NEW.condition IS NOT OLD.condition
           OR NEW.method IS NOT OLD.method OR NEW.seed IS NOT OLD.seed
           OR NEW.revision IS NOT OLD.revision OR NEW.finalized_at IS NOT OLD.finalized_at)
    BEGIN SELECT RAISE(ABORT, 'finalized reference is immutable; reopen it first'); END;
    CREATE TRIGGER annotation_notes_final_no_insert BEFORE INSERT ON annotation_notes
    WHEN (SELECT status FROM annotations WHERE id = NEW.annotation_id) = 'final'
    BEGIN SELECT RAISE(ABORT, 'finalized reference is immutable; reopen it first'); END;
    CREATE TRIGGER annotation_notes_final_no_update BEFORE UPDATE ON annotation_notes
    WHEN (SELECT status FROM annotations WHERE id = OLD.annotation_id) = 'final'
    BEGIN SELECT RAISE(ABORT, 'finalized reference is immutable; reopen it first'); END;
    """,
    # 6: provenance baseline (Codex review round 2). Whether contamination tracking covered the
    # database's entire life is recorded by migrate(); only 'complete' databases can hold a
    # validation dataset. Also: seen_audio backfilled from the event log (deleted sessions), and
    # references can only become final through the finalize path.
    """
    CREATE TABLE provenance_baseline (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        status TEXT NOT NULL CHECK (status IN ('complete', 'partial')),
        created_at_schema INTEGER NOT NULL,
        recorded_at TEXT NOT NULL
    );
    CREATE TRIGGER provenance_baseline_no_update BEFORE UPDATE ON provenance_baseline
    BEGIN SELECT RAISE(ABORT, 'provenance baseline is permanent'); END;
    CREATE TRIGGER provenance_baseline_no_delete BEFORE DELETE ON provenance_baseline
    BEGIN SELECT RAISE(ABORT, 'provenance baseline is permanent'); END;
    INSERT OR IGNORE INTO seen_audio
        SELECT audio_sha256, 'container', session_id, MIN(at) FROM provenance_events
        GROUP BY audio_sha256;
    CREATE TRIGGER annotations_insert_not_final BEFORE INSERT ON annotations
    WHEN NEW.status != 'draft'
    BEGIN SELECT RAISE(ABORT, 'references are created as drafts and finalized explicitly'); END;
    """,
]


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(db_path: Path) -> Iterator[sqlite3.Connection]:
    """One serialized transaction (BEGIN IMMEDIATE): reads and the writes based on them cannot
    interleave with another request's writes (no check-then-act races)."""
    conn = connect(db_path)
    conn.isolation_level = None  # explicit transaction control
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.close()


def migrate(db_path: Path) -> int:
    """Apply pending migrations; return the resulting schema version."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current = row[0] or 0
        started_at = current
        for version, script in enumerate(MIGRATIONS, start=1):
            if version <= current:
                continue
            conn.executescript(
                f"BEGIN; {script}; INSERT INTO schema_version VALUES ({version}); COMMIT;"
            )
            current = version
        # Record once whether this database was created with full provenance tracking. A database
        # that existed before migration 6 has history the guard cannot vouch for ('partial').
        conn.execute(
            "INSERT OR IGNORE INTO provenance_baseline "
            "(id, status, created_at_schema, recorded_at) "
            "VALUES (1, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            ("complete" if started_at == 0 else "partial", started_at),
        )
        conn.commit()
        return current
    finally:
        conn.close()
