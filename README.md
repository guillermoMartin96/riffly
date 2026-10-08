# JamRecall
Audio-first browser application to capture guitar improvisations, transcribe monophonic melodies, and save timestamped riffs.

## Status
Milestone 1 in progress on `feature/m1-audio-riff-slice`. Recording, persistence, playback and riffs work.
**No real transcription engine is enabled yet**: candidates are being benchmarked (`bench/`) and the choice awaits
tech-lead approval (`docs/decisions/requests/DR-0001-transcription-engine.md`). A test-only fixture adapter exists for
automated tests; its output is labelled in the UI as not derived from audio.

## Requirements (verified on macOS 26.2 x86_64)
- Python 3.11+ (developed with 3.12.15; system Python is not used)
- Node.js ≥ 20.19 (developed with 25.4.0, see `.nvmrc`; CI uses 22)
- No ffmpeg needed: audio decoding uses PyAV wheels, installed into the backend venv.

## Run locally
```sh
# backend (http://127.0.0.1:8000)
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m uvicorn --factory jamrecall.app:get_app --host 127.0.0.1 --port 8000

# frontend (http://127.0.0.1:5173, proxies /api to the backend)
cd frontend
npm ci
npm run dev
```
Data lives in `var/` (SQLite + original recordings) unless `JAMRECALL_DATA_DIR` is set. To try the UI's transcription
flow with fake data, start the backend with `JAMRECALL_TRANSCRIPTION_ENGINE=fixture JAMRECALL_ALLOW_TEST_ADAPTERS=1`
(the UI then shows a TEST FIXTURE banner).

## Tests
```sh
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest
cd frontend && npm run typecheck && npm test && npm run build
cd frontend && npx playwright install chromium && npm run e2e   # starts its own isolated servers
```
See `docs/proof/M1-proof.md` for recorded results.

## Privacy
Recordings are stored only on the local machine (`var/media/sessions/<id>/original.*`), served only on 127.0.0.1,
and never sent to external services. They are kept until you delete the `var/` directory (in-app session deletion is
deferred in M1; deleting a riff never deletes audio).
