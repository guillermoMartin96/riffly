# DR-0001 — Production transcription engine for M1
Status: **Approved provisionally** by the tech lead (2026-10-09). Engine stays "provisional" until the real-recording gate passes
Owner: Claude Code (implementation engineer)
Date: 2026-10-09

## Context and constraints
M1 needs a real engine that turns a recorded monophonic guitar phrase into timestamped MIDI notes behind
the existing `TranscriptionAdapter` contract (`backend/jamrecall/transcription/base.py`). It must run
locally (no cloud), on the supported dev machine (macOS 26.2, Intel x86_64, Python 3.12.15), with a
permissive licence and without changing system Python. Evidence: `docs/research/transcription-benchmark.md`.

## Option A — Basic Pitch 0.4.0, ONNX backend, monophonic post-process (recommended)
- GuitarSet holdout onset F1 0.906 / offset-aware 0.789. **Very likely inflated**: GuitarSet was in its training data.
- Synthetic holdout (uncontaminated) onset F1 **0.994** / offset-aware 0.873; strongest on fast riffs (0.992) and leaps (0.983).
- Warm real-time factor 0.0118 (≈7 threads); ≈0.082 CPU-s per audio-s; model load 2.19 s; peak RSS 309 MB.
- Apache-2.0. Install requires the documented `--no-deps` ONNX workaround; clean-install test PASS.
- Parameters: onset 0.7, frame 0.4, min note 58 ms, 75–1400 Hz, melodia trick, one note at a time.

## Option B — pYIN + onset segmentation (librosa 1.0.0)
- GuitarSet holdout onset F1 0.820 / 0.687; synthetic holdout 0.839 / 0.696; weak on fast riffs (0.600) and leaps (0.580).
- Warm real-time factor 0.081 (single thread, ≈0.079 CPU-s per audio-s); 11 s first-call JIT; peak RSS 653 MB.
- ISC licence, clean install, no training data (no contamination risk), actively maintained.

## Option C — no production engine yet
Ship recording/riffs without notes and report M1 incomplete, or gather more data first. M1 acceptance
requires real inference, so this delays M1.

## Measured evidence
`bench/results/summary.md`, `bench/results/{pyin,basic-pitch,fixture}.json`,
`bench/results/profile-{pyin,basic-pitch}.json`, clean-install log in the benchmark doc. The test-only
fixture scores F1 ≤ 0.005, confirming the metrics separate fixtures from real predictions.

## Recommendation and rationale
**Option A.** It beats pYIN by a wide margin on the uncontaminated synthetic corpus, especially on the fast
and leaping lines typical of improvised riffs, with lower memory and latency at similar total CPU. Its
GuitarSet lead is real-guitar evidence but cannot be taken at face value because of training-set overlap,
so **the decisive real-guitar check is the validation gate below**, scored on recordings neither engine
was trained or tuned on.

## Conditions attached to approval (from the tech lead, 2026-10-09)
1. CPU, peak-memory and model-load profiling completed before finalising — **done** (table above).
2. ONNX workaround accepted only if reproducible, fully pinned, clean-install test passes, deviations
   documented — **done on macOS x86_64**: `bench/requirements-basicpitch.lock`, `bench/clean_install_test.sh`
   PASS; deviations listed in the benchmark doc. Linux/CI install to be verified during integration.
3. Basic Pitch stays behind `TranscriptionAdapter`; replacing it must not change application behaviour.
4. pYIN preserved as benchmark baseline and potential fallback (kept in `bench/`; may be added as a
   second adapter behind the same interface).
5. **Validation gate**: a real guitar recording captured through JamRecall's browser microphone path,
   provided by the tech lead, is transcribed by the integrated engine and shown as tab. Proposed pass
   criteria (for approval): the tech lead annotates the played notes (or plays a known phrase); the
   recording is scored with the benchmark scorer for Basic Pitch and pYIN; Basic Pitch onset F1 ≥ 0.80
   and not below pYIN. If it fails, stop and raise a scope/quality decision rather than ship.
6. Known limitation: no electric-guitar recordings in the evidence.
7. PyAV/FFmpeg licensing review opened separately (DR-0002); not blocking local M1 development.
8. M1 not claimed complete until the recording → transcription → tablature workflow is validated
   against M1 acceptance criteria.

## Cost, risk, reversibility
- Cost: ~170 MB more venv than pYIN-only (onnxruntime, scikit-learn, etc.); +2.2 s model load per
  backend process (load once at startup).
- Risks: unmaintained since 2024 and incompatible metadata (workaround may break with future numpy /
  setuptools); GuitarSet contamination; untested on electric guitar, browser Opus audio and laptop mics;
  multithreaded inference competes with other local work.
- Reversibility: high. Engine choice is one adapter registration plus pinned deps; persisted notes keep
  engine name and version, so outputs from different engines remain distinguishable. Rollback = select
  the pYIN adapter or no engine via `JAMRECALL_TRANSCRIPTION_ENGINE`.

## Decision needed from tech lead
1. Final approval to integrate Option A as the default engine (adapter, pinned deps, CI install).
2. Approval of the proposed pass criteria for the validation gate (condition 5).
3. Whether pYIN should also be integrated now as a selectable fallback adapter, or kept in `bench/` only.

## Decision and date (leave blank pending approval)
**2026-10-09: tech lead decision** (recorded verbatim in substance; the implementer did not self-approve)

1. **Option A approved provisionally.** Integrate Basic Pitch 0.4.0 (ONNX) behind the existing
   adapter. Keep the pinned environment, add clean-install and inference smoke tests to CI, and keep
   the engine configurable and replaceable. Do not mark it fully validated until independent
   real-guitar testing passes. Keep benchmark reproducibility and document the GuitarSet overlap.
2. **Modified real-recording criteria approved.** Aggregate gate: onset F1 ≥ 0.80 and Basic Pitch ≥ pYIN.
   Validation must cover clean acoustic melodies, fast riffs and wide leaps, and clean electric guitar,
   plus distorted electric as an exploratory test that does not block M1. Recordings must not be known
   to be in Basic Pitch's training data. References come from manual annotation or known
   score/MIDI performances. Report onset F1, pitch correctness, note-end quality, per-recording results
   and latency. Define tolerances and scoring first. Tune only on a separate dev set, never on the
   holdout. On failure or a poorly performing condition: stop and raise a decision request.
3. **pYIN stays in the benchmark only**: kept and compatible, not selectable in production.

### Implementation status (2026-10-09)
| Condition | Status |
|---|---|
| Adapter behind `TranscriptionAdapter`, configurable (`JAMRECALL_TRANSCRIPTION_ENGINE`, `none` disables) | Done: `backend/jamrecall/transcription/basic_pitch_adapter.py` |
| Pinned environment | Done: `backend/requirements.lock` + `backend/install.sh`. Only deviation from the bench lock: `typing_extensions` 4.15.0 → 4.16.0 (needed by pydantic; basic-pitch has no upper bound). Parity test proves identical notes |
| Clean-install + inference smoke tests in CI | Done: CI builds with `--no-cache-dir` via `install.sh` (pip-check guard) on ubuntu-24.04; `tests/test_basic_pitch.py` runs as its own step |
| Provisional status visible | Done: `validated=false` in `/api/config`; UI shows "(provisional)" and a warning |
| GuitarSet overlap documented | Done: `docs/research/transcription-benchmark.md` |
| Validation protocol defined before evaluation | Done: `docs/research/real-recording-validation-protocol.md`, tooling `bench/jamrecall_bench/real.py` (dry run on synthetic audio only) |
| Real-recording gate | **Pending recordings from the tech lead** |
| pYIN benchmark-only | Done: not registered in `REAL_ADAPTERS`; bench code unchanged |
