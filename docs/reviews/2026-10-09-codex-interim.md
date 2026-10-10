# Review record
PR / branch / commit: draft PR #1, feature/m1-audio-riff-slice @ 225c8d2 (interim review)
Reviewer and model/provider: OpenAI Codex CLI 0.162.0 (`codex exec -s read-only`), independent of the implementer
Scope reviewed: all changes on the branch vs main (backend, frontend, bench, docs)
Commands and tests actually run: Codex inspected the diff and made in-memory reproductions; it did not rerun the full suite
Findings (severity, file/line, reproduction):
1. BLOCKING bench/jamrecall_bench/real.py gate — scores are not bound to the current manifest (IDs, hashes, revisions); missing per-condition summaries are skipped → false PASS possible. **Fixed**: manifest content fingerprint; results record the fingerprint and scored ids; gate (pure `evaluate_gate`) reports INCOMPLETE on mismatch or missing summaries (bench/tests/test_real.py)
2. BLOCKING real.py prepare — duplicate session/audio hash can inflate counts and leak dev↔holdout. **Fixed**: duplicates refused across splits; no manifest written on any error; notes past the recording end refused (tests)
3. MAJOR app.py/audio.py — duration limit enforced after unbounded decode; decode blocked the event loop. **Fixed**: limit enforced during decode, huge start times refused before allocation, decode in a threadpool (tests `test_decode_timeline.py`)
4. MAJOR audio.py — timestamp gaps discarded. **Fixed**: frames placed by timestamp; gaps become silence; out-of-order timestamps rejected; ≤10 ms jitter tolerated (tests)
5. MAJOR frontend usePlayer.ts — riff end enforced only by requestAnimationFrame (paused in background tabs). **Fixed**: end also enforced by a scheduled timer and `timeupdate`; E2E `playback.spec.ts` with rAF disabled (fails on old code, passes now)
6. MAJOR usePlayer.ts — loop ending at the recording end stops on `ended`. **Fixed**: `ended` inside a looping range wraps to the start; E2E with a riff ending at the server-measured duration (fails on old code, passes now)
7. MAJOR real.py — missing `status`/`seed` default to final/blank. **Fixed**: both required and validated; protocol example updated
8. MAJOR real.py — `--tune-on-dev` can validate parameters the app does not run. **Fixed**: app and scorer share `basic_pitch_params.json`; a tuned or mismatched result cannot PASS; backend test asserts the app params equal the benchmark selection
9. MINOR annotations.py / riff endpoint — validation before rounding → DB constraint error. **Fixed** (test added)
10. MINOR real.py — "excluding technique notes" metric keeps the matching estimates (false positives). **Fixed**: estimates matched to tagged notes are removed too (test)
Fixes and retest evidence (macOS, 2026-10-09): backend 65 passed; bench gate tests 12 passed; vitest 43 passed; Playwright 8 passed (incl. 2 new playback tests verified to fail on the pre-fix code). Follow-up Codex verification: see below.
Remaining risks: all 10 findings addressed; real-guitar validation still pending recordings

## Verification round 1 (Codex, read-only, on commits 6f1a5f3 + cf0ae07)
Verdict: 6 verified fixed (2, 3, 4, 5, 6, 7); 4 partially fixed, each with a reproduction; no new blocking/major issues.
- 1 partial: the fingerprint omitted the analysed audio file. **Fixed**: manifest records each analysis WAV's sha256;
  the fingerprint covers the path and hash; `score` refuses audio that changed after `prepare`.
- 8 partial: frequency bounds were not compared. **Fixed**: results record the full app parameter set; the gate compares
  all of it to `basic_pitch_params.json`.
- 9 partial: the riff end was clamped after validation (start 1.0, end 1.000001 on a 1.0 s take → DB error).
  **Fixed**: clamp, then validate the stored values (riffs and annotations).
- 10 partial: greedy onset-only removal ignored pitch. **Fixed**: uses the scorer's own optimal onset+pitch matching
  (mir_eval); only estimates matched to tagged notes are dropped.
Retest (macOS): backend 66 passed; bench gate tests 16 passed. Each new test was confirmed to fail on the previous code
(4 bench tests; the riff clamping test reproduced `CHECK constraint failed`).
Caveat noted by Codex: the background-tab test simulates suspended animation frames, not real browser timer throttling.

## Verification round 2 (Codex, read-only, on 5761da8)
Findings 1, 8, 9, 10: **all verified fixed** against the round-1 reproductions; no new blocking or major problems.
CI run 38016950913 (ubuntu-24.04) on 5761da8: backend 11 + 55, bench gate 16, frontend 43, Playwright 8 — all passed.

**Status: all 10 interim findings resolved and independently verified.** Open item outside the review's scope:
real-guitar validation (waiting for the tech lead's recordings).

Tech-lead disposition:
