# JamRecall
Audio-first browser application to capture guitar improvisations, transcribe monophonic melodies, and save timestamped riffs.

## Status
Milestone 1 in progress on `feature/m1-audio-riff-slice`. Recording, persistence, playback, riffs and
transcription work end to end. The engine is **Basic Pitch 0.4.0 (ONNX)**, provisionally approved in
`docs/decisions/requests/DR-0001-transcription-engine.md` and labelled *provisional* in the UI until it
passes validation on real guitar recordings (`docs/research/real-recording-validation-protocol.md`).
**M1 is not complete** until that gate passes.

## Requirements (verified on macOS 26.2 x86_64)
- Python 3.11+ (developed with 3.12.15; system Python is not used)
- Node.js ≥ 20.19 (developed with 25.4.0, see `.nvmrc`; CI uses 22)
- No ffmpeg needed: audio decoding uses PyAV wheels, installed into the backend venv.

## Run locally
```sh
# backend (http://127.0.0.1:8000); install.sh pins everything and adds basic-pitch with --no-deps (DR-0001)
sh backend/install.sh
cd backend && .venv/bin/python -m uvicorn --factory jamrecall.app:get_app --host 127.0.0.1 --port 8000

# frontend (http://127.0.0.1:5173, proxies /api to the backend)
cd frontend
npm ci
npm run dev
```
Data lives in `var/` (SQLite + original recordings) unless `JAMRECALL_DATA_DIR` is set. The backend loads the
Basic Pitch model at startup (~4 s extra). `JAMRECALL_TRANSCRIPTION_ENGINE=none` disables transcription;
`fixture` + `JAMRECALL_ALLOW_TEST_ADAPTERS=1` selects the test-only adapter, which the UI labels TEST FIXTURE.

## Tests
```sh
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest   # incl. real inference
cd frontend && npm run typecheck && npm test && npm run build
cd frontend && npx playwright install chromium && npm run e2e   # starts its own isolated servers
```
See `docs/proof/M1-proof.md` for recorded results.

## Privacy
Recordings are stored only on the local machine (`var/media/sessions/<id>/original.*`), served only on 127.0.0.1,
and never sent to external services. They are kept until you delete the `var/` directory (in-app session deletion is
deferred in M1; deleting a riff never deletes audio; every transcription run is kept). Retention policy: DR-0003 (proposed).
Licensing inventory and pre-deployment obligations: DR-0002.
