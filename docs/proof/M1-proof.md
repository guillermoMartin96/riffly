# M1 Proof checklist
- [x] Local startup commands and supported environment recorded — `README.md`, `docs/milestones/M1-implementation-plan.md` (Environment)
- [x] Frontend/backend unit and integration test commands and results — see Evidence log
- [ ] Browser E2E record/save/reload/replay demonstration — passes with the TEST-ONLY fixture engine; must be rerun with the approved real engine
- [x] Permission-denied and missing-device scenarios — permission denial is real Chromium behaviour; missing device is **simulated** (getUserMedia stubbed to reject `NotFoundError`)
- [ ] Recorded source audio integrity and duration verification — sha256 round-trip and duration checks pass in pytest and E2E; still needs a real microphone take
- [ ] Real inference demonstration (not fixture data) — pending DR-0001 final approval and the tech lead's recording
- [x] Benchmark dataset and annotation provenance — `docs/research/transcription-benchmark.md`
- [x] Note precision/recall/F1, onset tolerance, pitch error, processing-time measurements — `bench/results/`
- [ ] String/fret ambiguity and unsupported-technique disclosure — implemented in the UI; needs to be shown on real transcription output
- [ ] Riff interval boundaries, looping, persistence, deletion semantics — covered by tests; to be re-verified on a real recording
- [ ] Security/privacy review and upload/retention description — retention is described in `README.md`; formal review pending; licensing review open (DR-0002)
- [ ] Independent review findings resolved or explicitly accepted — PR and Codex review not started

Record actual commands, outputs, environment, timestamps, and links to evidence. Never precheck without running.

## Evidence log

### 2026-10-08 — tests (macOS 26.2 x86_64, Python 3.12.15, Node 25.4.0)
| Command | Result |
|---|---|
| `cd backend && .venv/bin/ruff check . && .venv/bin/pytest` | All checks passed; **39 passed** |
| `cd frontend && npx tsc -b && npx vitest run && npx vite build` | typecheck OK; **21 passed**; build OK |
| `cd frontend && npx playwright test` (mic mode `webaudio` on macOS) | **4 passed**: workflow, permission denied, no device (simulated), processing failure + missing audio |
| GitHub Actions run 37857279006 (ubuntu-24.04, Node 22, Python 3.12, mic mode `device`) | backend ✓ (39), frontend ✓ (21), e2e ✓ (4) |

E2E caveats: the transcription engine is the **TEST-ONLY fixture**, which the UI labels "NOT derived from
this recording". The test input is a synthetic pluck WAV. On macOS, Chromium's audio capture blocks on the
OS microphone permission of the host terminal app (video capture works), so audio is injected as a Web
Audio `MediaStream`. MediaRecorder encoding, upload, decoding, persistence and playback are real in both
modes. Screenshots: `frontend/test-results/evidence/` (CI artifact `e2e-evidence`).

### 2026-10-09 — transcription benchmark
Commands: see `bench/README.md`. Results: `bench/results/summary.md`. Holdout onset F1: Basic Pitch (mono)
0.906 on GuitarSet (contaminated: training data overlap) and 0.994 on synthetic; pYIN 0.820 and 0.839;
fixture 0.002 and 0.004. Profiling, warm real-time factor: Basic Pitch 0.0118, pYIN 0.081. Peak RSS:
Basic Pitch 309 MB, pYIN 653 MB. Basic Pitch clean-install test: PASS (`bench/clean_install_test.sh`).
