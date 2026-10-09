# M1 implementation plan — audio-to-riff vertical slice

Branch: `feature/m1-audio-riff-slice` (from `main` @ d8b4b64). Living document; updated as work lands.

## Environment (inspected 2026-10-08)

| Item | Found | Decision |
|---|---|---|
| OS / CPU | macOS 26.2, Intel i9-9880H **x86_64**, 16 threads, 32 GB | All deps must ship macOS x86_64 wheels |
| System Python | 3.9.6 (`/usr/bin/python3`) | Not touched |
| Python 3.12.15 | uv-managed, `~/.local/bin/python3.12` | Project venvs (`backend/.venv`, `bench/.venv`) |
| Node | nvm: 11.7, 18.7, **25.4.0** | Use 25.4.0 locally (`.nvmrc`); CI on Node 22 LTS. Vite 7 needs ≥20.19 |
| ffmpeg | not installed | Not installed; decode with PyAV wheels (bundled FFmpeg libs, venv-local) |
| SQLite | 3.53 (Python stdlib module) | stdlib `sqlite3`, no ORM |
| git remote / gh | `origin` reachable, gh authenticated | Push feature branch; PR at end |

Compatibility probes (scratch venvs, Python 3.12, x86_64):
- `librosa 1.0.0` (+ numba 0.62.1, numpy 2.3.5) and `av 19.0.1` install from wheels; `librosa.pyin` runs.
- `basic-pitch 0.4.0` **does not install normally**: on Darwin + Python >3.11 it requires `tensorflow-macos<2.15.1`, which has no 3.12 wheels. Workaround that runs: `pip install --no-deps basic-pitch==0.4.0` + `onnxruntime 1.23.2` + `resampy<0.4.3` + `setuptools<81` (resampy imports `pkg_resources`), using the bundled `nmp.onnx` model. This is installation friction and is scored as such.
- `aubio`: no binary wheel (would need a compiler toolchain) — not used.

## Architecture

```
frontend/  React 19 + TypeScript + Vite 7 (dev proxy /api -> 127.0.0.1:8000)
backend/   FastAPI + stdlib sqlite3 + PyAV decode; package `jamrecall`
bench/     transcription benchmark: corpus builders, candidate runners, metrics, results
var/       (git-ignored) runtime data: jamrecall.sqlite3 + media/sessions/<id>/original.<ext>
```

Principles applied: original upload stored byte-for-byte (sha256 recorded) and never rewritten; all times
are seconds on the decoded source-audio clock; riffs reference `session_id` + `[start,end)`; detected
pitch and inferred fingering are separate fields; transcription engines sit behind a versioned adapter.

## Data schema (SQLite, `schema_version` table for migrations)

- `sessions(id TEXT PK, audio_path, audio_mime, audio_bytes, audio_sha256, duration_seconds REAL, sample_rate, created_at, status)` — status: `ready` | `audio_missing` (computed on read).
- `transcriptions(id PK, session_id FK, engine, engine_version, test_only INT, status, error, fingering_method, created_at, completed_at, processing_seconds)` — status: `pending|running|succeeded|failed`.
- `note_events(id PK, transcription_id FK, start_seconds, end_seconds, midi_pitch, confidence NULL, string NULL, fret NULL, fingering_alternatives INT)` — CHECKs: `start>=0`, `end>start`, `midi 0..127`, string 1..6.
- `riffs(id PK, session_id FK, title, start_seconds, end_seconds, created_at)` — CHECK `0<=start<end`; `end<=duration` validated in API.

## API routes

| Method / path | Purpose |
|---|---|
| `GET /api/health` | liveness + db check |
| `GET /api/config` | configured transcription engine (+ `test_only` flag), accepted MIME types, limits |
| `POST /api/sessions` | multipart upload (`audio`, `client_mime`); validate non-empty, MIME allow-list, size limit, decodable, duration > 0 |
| `GET /api/sessions`, `GET /api/sessions/{id}` | list / detail (reports `audio_missing`) |
| `GET /api/sessions/{id}/audio` | original bytes, HTTP Range support; 404 `audio_missing` if file gone |
| `GET /api/sessions/{id}/peaks?n=` | waveform peaks from decoded audio |
| `POST /api/sessions/{id}/transcriptions` | start transcription with configured engine (background task) |
| `GET /api/sessions/{id}/transcriptions/latest` | status, engine provenance, error, notes + fingering |
| `POST /api/sessions/{id}/riffs`, `GET /api/sessions/{id}/riffs` | create (validated) / list riffs |
| `GET /api/riffs`, `GET /api/riffs/{id}`, `DELETE /api/riffs/{id}` | list all / detail / delete riff (audio kept) |

Session deletion is deferred (M1 non-goal). Server binds 127.0.0.1 only.

## Transcription adapter contract

`TranscriptionAdapter`: `engine`, `version`, `test_only`, `transcribe(AudioBuffer) -> list[DetectedNote]`,
raising `TranscriptionError(reason)`. `AudioBuffer` = mono float32 PCM + sample rate decoded from the
original file. Output is normalized (sorted, `0 <= start < end <= duration`, MIDI int 0–127, confidence
in [0,1] or null) before persistence. Adapters:
- `fixture` — deterministic, **test-only**, ignores audio content; enabled only with
  `JAMRECALL_ALLOW_TEST_ADAPTERS=1`; UI shows a "TEST FIXTURE — not derived from audio" banner.
- `failing` — test-only, always raises (error-path tests).
- Real engine — **not selected**. Candidates are benchmarked in `bench/`; integration waits for
  tech-lead approval of a decision request (DR-0001). Without an engine configured the UI reports
  "transcription unavailable" rather than showing notes.

Fingering: standard tuning E2 A2 D3 G3 B3 E4 (MIDI 40 45 50 55 59 64), frets 0–20. Dynamic
programming over all candidate positions minimizing hand movement; every result satisfies
`open_string_midi + fret == midi_pitch`; number of alternatives stored and shown; out-of-range pitches
get null string/fret.

## UI flows

1. Record: detect `MediaRecorder` + `isTypeSupported` over `audio/webm;codecs=opus`, `audio/ogg;codecs=opus`,
   `audio/mp4`; states idle → requesting → recording → uploading → saved; errors for permission denied
   (`NotAllowedError`), no device (`NotFoundError`), unsupported API, empty recording, upload failure.
2. Session view: waveform + time ruler + playback cursor; note lane and 6-line tab aligned to the same
   time axis; engine/provenance banner; fingering labelled "inferred".
3. Select range by drag or numeric inputs; validation messages; name + save riff.
4. Riff list: play once (stops at end) / loop / delete; persists across reload.

## Tests

- Backend (pytest): upload validation & integrity (sha256, duration), Range serving, missing audio,
  riff validation (negative, reversed, zero-length, beyond duration, NaN, unknown session), delete
  semantics, reload persistence (new app instance on same db), adapter normalization, failure
  persistence, test-adapter gating, fingering property tests.
- Frontend (vitest + Testing Library): MIME selection, recorder error mapping, selection validation,
  time formatting, tab layout.
- E2E (Playwright, Chromium with fake audio capture fed from a WAV file): record → save → (transcribe)
  → select → save riff → reload → timestamps equal → play/loop → delete; permission denied; no device;
  processing failure; missing audio.
- CI (GitHub Actions): ruff + pytest; tsc + vitest + build; Playwright E2E.

## Transcription (gates C/D) — status 2026-10-09

- Benchmark complete (`docs/research/transcription-benchmark.md`). DR-0001 Option A **approved
  provisionally**; Basic Pitch 0.4.0 (ONNX) is integrated as the default engine behind
  `TranscriptionAdapter` and labelled "provisional" until the real-recording gate passes.
- Pipeline layers: capture (browser MediaRecorder) → preprocessing (`audio.decode_mono`, 22,050 Hz mono)
  → inference (`BasicPitchAdapter`) → post-processing (`postprocess.monophonic`) → normalized note events
  (`DetectedNote`: onset, offset, MIDI pitch, confidence) → fingering inference (`fingering.py`) → presentation.
- Every transcription run is kept (history endpoint) for re-transcription and future corrections (DR-0003 proposed).
- pYIN stays benchmark-only (DR-0001 decision 3). Licensing: DR-0002 (open, non-blocking).
- **Remaining M1 gate**: real-recording validation (protocol + tooling ready; waiting for recordings).

## Risks

- Chrome MediaRecorder WebM lacks duration/cues → browser `duration` may be `Infinity`; server-measured
  duration is canonical and the UI uses it.
- AAC (`audio/mp4`, Safari) encoder priming may offset decoded vs. played timeline; tested where possible.
- No electric-guitar recordings in the evidence (known limitation, DR-0001). I can't play guitar, so the
  tech lead will provide a microphone take for the validation gate.
- Basic Pitch training-set overlap with GuitarSet inflates its GuitarSet scores.
- PyAV wheel bundles GPL x264/x265 libraries next to LGPL FFmpeg; licensing review DR-0002 must finish before distribution.
- macOS: Chromium audio capture blocks on the host app's OS microphone permission, so E2E injects audio via Web Audio there.
- Basic Pitch install relies on a `--no-deps` workaround; pinned and documented if chosen.
- pYIN is CPU-heavy; latency measured, not assumed.
