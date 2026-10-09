# DR-0003 — Retention of recordings and transcription outputs; basis for future corrections
Status: Proposed — needs tech-lead decision (privacy/retention, per CLAUDE.md)
Owner: Claude Code (implementation engineer)
Date: 2026-10-09

## Context and constraints
Engineering requirement 6 (2026-10-09): keep the original audio and note-event outputs in a way that
supports future user corrections and re-transcription, subject to explicit retention and privacy
decisions. What M1 does today:
- The original upload is stored byte-for-byte (`var/media/sessions/<id>/original.*`, sha256 in SQLite),
  only on the local machine and served only on 127.0.0.1. Nothing is sent to external services.
- Every transcription run is a new `transcriptions` row with its engine name and version (including
  parameters), status, error, stage timings and immutable `note_events`. Re-transcribing never
  overwrites earlier output. `GET /api/sessions/{id}/transcriptions` lists the history.
- Detected pitch (engine output) and inferred fingering are stored as separate fields.
- Deleting a riff never deletes audio. There is no in-app session deletion (deferred in M1). Data is kept
  until the user deletes `var/`. There is no retention limit and no export.

## Option A — keep everything until the user deletes it (current behaviour, made explicit) (recommended for M1)
Local-only; keep originals and all transcription runs indefinitely. Document how to delete everything
(`var/`). Future corrections are stored as a separate edit layer (`note_corrections` referencing
`transcription_id` and a note) so engine output stays reproducible and comparable.
Cost: none now. Risk: unbounded local disk use. Reversible.

## Option B — keep originals; prune old transcription runs
Keep the latest N runs per session (or the runs referenced by corrections).
Cost: small. Loses engine-comparison history.

## Option C — add user deletion and retention controls now
In-app session deletion (cascading riffs, transcriptions and audio), a retention period, export.
Cost: M1 scope increase (session deletion is an M1 non-goal).

## Measured evidence
Tests: `test_retranscription_keeps_history`, `test_delete_riff_keeps_session_audio_and_sibling_riffs`,
`test_upload_wav_stores_original_bytes_and_measures_duration` (sha256 round-trip), E2E step 8.

## Recommendation and rationale
**Option A for M1.** It satisfies the requirement without adding scope, and the data never leaves the
machine. Before any hosted or multi-user milestone, Option C plus a written privacy notice becomes necessary.

## Cost, risk, reversibility
Option A has no cost and is fully reversible. Correction storage is designed (separate layer) but not
built in M1, because note editing is an M1 non-goal.

## Decision needed from tech lead
Approve Option A (local, indefinite, user-deletable via `var/`) as the M1 retention policy, or choose B/C.

## Decision and date (leave blank pending approval)
