# Review record
PR / branch / commit: draft PR #1, feature/m1-audio-riff-slice @ 225c8d2 (interim review)
Reviewer and model/provider: OpenAI Codex CLI 0.162.0 (`codex exec -s read-only`), independent of the implementer
Scope reviewed: all changes on the branch vs main (backend, frontend, bench, docs)
Commands and tests actually run: Codex inspected the diff and made in-memory reproductions; it did not rerun the full suite
Findings (severity, file/line, reproduction):
1. BLOCKING bench/jamrecall_bench/real.py gate — scores are not bound to the current manifest (IDs, hashes, revisions); missing per-condition summaries are skipped → false PASS possible. **Open**
2. BLOCKING real.py prepare — duplicate session/audio hash can inflate counts and leak dev↔holdout. **Open**
3. MAJOR app.py/audio.py — duration limit enforced after unbounded decode; decode blocked the event loop. **Fixed**: limit enforced during decode, huge start times refused before allocation, decode in a threadpool (tests `test_decode_timeline.py`)
4. MAJOR audio.py — timestamp gaps discarded. **Fixed**: frames placed by timestamp; gaps become silence; out-of-order timestamps rejected; ≤10 ms jitter tolerated (tests)
5. MAJOR frontend usePlayer.ts — riff end enforced only by requestAnimationFrame (paused in background tabs). **Open**
6. MAJOR usePlayer.ts — loop ending at the recording end stops on `ended`. **Open**
7. MAJOR real.py — missing `status`/`seed` default to final/blank. **Open**
8. MAJOR real.py — `--tune-on-dev` can validate parameters the app does not run. **Open**
9. MINOR annotations.py / riff endpoint — validation before rounding → DB constraint error. **Fixed** (test added)
10. MINOR real.py — "excluding technique notes" metric keeps the matching estimates (false positives). **Open**
Fixes and retest evidence: backend 64 passed locally after the fixes for 3, 4 and 9 (macOS, 2026-10-09)
Remaining risks: findings 1, 2, 5, 6, 7, 8 and 10 are open; the real-guitar gate must not be run until 1, 2, 7 and 8 are fixed
Tech-lead disposition:
