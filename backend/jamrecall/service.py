"""Transcription job: decode the original recording, run the adapter, persist normalized notes."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from jamrecall import fingering, store
from jamrecall.audio import AudioDecodeError, decode_mono
from jamrecall.config import Settings
from jamrecall.db import transaction
from jamrecall.transcription.base import TranscriptionAdapter, normalize_notes

log = logging.getLogger(__name__)


def run_transcription(settings: Settings, adapter: TranscriptionAdapter, tid: str) -> None:
    with transaction(settings.db_path) as conn:
        t = store.get_transcription(conn, tid)
        session = store.get_session(conn, t["session_id"]) if t else None
        if t is None or session is None:
            return
        store.mark_transcription(conn, tid, "running")

    started = time.perf_counter()
    try:
        path = settings.data_dir / session["audio_path"]
        if not Path(path).is_file():
            raise FileNotFoundError("audio_missing: original recording file not found")
        audio = decode_mono(path, adapter.sample_rate)
        raw = adapter.transcribe(audio)
        notes = normalize_notes(raw, session["duration_seconds"])
        fingerings = fingering.assign([n.midi_pitch for n in notes])
    except (AudioDecodeError, FileNotFoundError) as exc:
        _fail(settings, tid, str(exc), started)
        return
    except Exception as exc:  # engine errors, including TranscriptionError
        log.exception("transcription %s failed", tid)
        _fail(settings, tid, f"{type(exc).__name__}: {exc}", started)
        return

    with transaction(settings.db_path) as conn:
        store.insert_notes(conn, tid, notes, fingerings)
        store.mark_transcription(
            conn,
            tid,
            "succeeded",
            fingering_method=fingering.METHOD,
            processing_seconds=round(time.perf_counter() - started, 4),
            completed_at=store.now_iso(),
        )


def _fail(settings: Settings, tid: str, reason: str, started: float) -> None:
    with transaction(settings.db_path) as conn:
        store.mark_transcription(
            conn,
            tid,
            "failed",
            error=reason[:1000],
            processing_seconds=round(time.perf_counter() - started, 4),
            completed_at=store.now_iso(),
        )
