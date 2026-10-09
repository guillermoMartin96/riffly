# M1 Proof checklist
- [x] Local startup commands and supported environment recorded — `README.md`, `docs/milestones/M1-implementation-plan.md` (Environment)
- [x] Frontend/backend unit and integration test commands and results — see Evidence log
- [x] Browser E2E record/save/reload/replay demonstration — real Basic Pitch engine, browser-recorded Opus/WebM; mic input is a synthetic pluck phrase (see 2026-10-09)
- [x] Permission-denied and missing-device scenarios — permission denial is real Chromium behaviour; missing device is **simulated** (getUserMedia stubbed to reject `NotFoundError`)
- [x] Recorded source audio integrity and duration verification — sha256 round-trip + server-measured duration on browser-recorded audio (E2E) and on WAV/Opus/AAC (pytest); to be repeated on the tech lead's microphone takes
- [ ] Real inference demonstration (not fixture data) — the real engine runs end to end in the app (E2E, Linux and macOS) on **synthetic** input; a **real guitar** recording through the browser is still pending (validation gate)
- [x] Benchmark dataset and annotation provenance — `docs/research/transcription-benchmark.md`
- [x] Note precision/recall/F1, onset tolerance, pitch error, processing-time measurements — `bench/results/`
- [x] String/fret ambiguity and unsupported-technique disclosure — shown on real-engine output (`02-transcribed.png`): inferred-fingering label, underlined ambiguous frets, techniques-not-modelled notice, provisional-engine warning
- [x] Riff interval boundaries, looping, persistence, deletion semantics — E2E with the real engine: invalid ranges rejected, exact [0.5, 1.75) persisted across reload, play stops at end (1.70–1.85 s), loop wraps, delete keeps audio and transcription history
- [ ] Security/privacy review and upload/retention description — retention described (`README.md`, DR-0003 proposed); licensing inventory and obligations in DR-0002 (open, non-blocking); formal review pending
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

### 2026-10-09 — Basic Pitch integration (DR-0001, provisionally approved)
| Command | Result |
|---|---|
| `PIP_FLAGS=--no-cache-dir sh backend/install.sh` (macOS x86_64) | clean install OK in 116 s, pip-check guard passed; venv 669 MB |
| `cd backend && .venv/bin/ruff check . && .venv/bin/pytest` | All checks passed; **49 passed** (incl. 10 Basic Pitch inference tests) |
| `cd frontend && npx tsc -b && npx vitest run` | **22 passed** |
| `cd frontend && npx playwright test` (macOS, mic mode `webaudio`) | **4 passed**; real engine detected the played phrase exactly: `[57,60,62,64,67,64,62]` |
| GitHub Actions run 37983088726 (ubuntu-24.04, mic mode `device`) | backend ✓ (Linux clean install, 10 inference + 39 other tests), frontend ✓ (22), e2e ✓ (4) |

Inference tests (`backend/tests/test_basic_pitch.py`, synthetic plucks encoded like browsers record):
WAV 44.1/48 kHz, Opus/WebM 48 kHz (Chrome/Firefox), Opus/Ogg 48 kHz, AAC/MP4 44.1 kHz (Safari).
In every format the exact pitch sequence is detected, with all onsets within 50 ms of the source clock.
Parity: the app adapter reproduces the benchmark pipeline's notes exactly.

End-to-end latency, 4.98 s browser recording (`test-results/evidence/latency.json`):
| Stage | macOS (webaudio) | Linux CI (device) |
|---|---|---|
| Stop → session shown (upload + server decode/verify + UI) | 0.23 s | 0.14 s |
| Server decode | 0.025 s | 0.021 s |
| Server inference | 0.127 s | 0.218 s |
| Click "Transcribe" → status succeeded (incl. ≤ 250 ms polling) | 0.34 s | 0.36 s |
| Click "Transcribe" → tab rendered | 0.35 s | 0.37 s |

Initialization: backend cold start to first healthy response, 3 runs each on macOS: **1.4–1.7 s without
an engine vs 5.5–6.1 s with Basic Pitch** (imports + ONNX session; `model_load_seconds` in `/api/config`
covers only the ONNX session, ≈0.03 s). Paid once per backend process.

Real-recording validation: protocol defined before evaluation
(`docs/research/real-recording-validation-protocol.md`). Tooling dry run on the synthetic E2E session
gave verdict INCOMPLETE (exit 2) as designed, and a sha256-mismatched reference was refused. **No real
recordings evaluated yet.**

### 2026-10-09 — manual-testing workflow (annotation, export, deletion)
| Command | Result |
|---|---|
| `cd backend && .venv/bin/pytest` | **58 passed** (adds 9 annotation/export/deletion/CLI/migration tests) |
| `cd frontend && npx vitest run` | **43 passed** (adds pitch parsing and annotation rules) |
| `cd frontend && npx playwright test` (macOS, `webaudio`) | **6 passed**, incl. `annotation.spec.ts`: start from model output → delete false positive → fix pitch (F#4) → nudge +10 ms → add missed note at 4.600 s → save → reload (persisted; **model output byte-identical**) → overlap rejected → finalize (split locked) → export zip (original audio, reference, runs, metadata; sha256 intact) → delete recording (rows + media gone); holdout + model seed shows a warning |
| `./scripts/dev.sh` with Node 18.7 on PATH | switches to Node 25.4.0 via nvm; API on 8700, app on 5173; refuses a busy port (port 8000 is held by an unrelated local FastAPI app) |
| `jamrecall_bench.real` dry run (synthetic E2E take) | model-seeded holdout reference excluded; verdict INCOMPLETE (exit 2) |

Timing finding: for Chrome MediaRecorder WebM the browser `duration` (4.977 s) is one 60 ms Opus frame
shorter than the decoded length (5.037 s). The first packet pts is 0 and the Opus pre-skip is 0, so the
start is aligned and notes and riffs match playback (assumption 13).
Screenshot: `frontend/test-results/evidence/20-annotation.png`.
