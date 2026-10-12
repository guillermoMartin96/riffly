# Review record
PR / branch / commit: draft PR #1, `feature/m1-audio-riff-slice`. Change under review: holdout contamination guard
(tech-lead approval 2026-10-12), commits `9c775fa` … `16c3404`.
Reviewer and model/provider: OpenAI Codex CLI 0.162.0 (`codex exec -s read-only`), independent of the implementer.
Seven rounds, each verifying the previous round's reproductions and searching for new ways ineligible holdout data
could count.
Scope reviewed: backend provenance (`backend/jamrecall/provenance.py`, migrations 4–6 in `db.py`, API/export/CLI
paths), the validation gate (`bench/jamrecall_bench/real.py`), UI warnings, tests and docs. Thresholds, minimums and
scoring were checked against `9188701` in every round.
Commands and tests actually run: Codex inspected the diffs and ran in-memory reproductions (read-only; no full
suites). The implementer reran all suites locally after every fix; CI on each commit is listed below.

Findings (severity, file/line, reproduction) and fixes:

| Round | Reviewed | Verdict | Findings | Fixed in |
|---|---|---|---|---|
| 1 | `9c775fa` | FAIL | **B1** concurrent reopen skipped contamination · **B2** post-finalization transcription then identical re-upload stayed eligible · **B3** manifest identity substitution · **B4** editable score summaries / inclusion lists · **M5** migration promoted legacy recordings to clean · **M6** editing exported references bypassed reopen · **M7** container re-wrap of the same samples counted as new | `7bfd3ce`: `BEGIN IMMEDIATE` + ordering/immutability triggers; permanent `seen_audio` (container + decoded hash); only in-app recordings tracked from creation are eligible; gate redesigned as one `validate` run that reads only the DB and original audio |
| 2 | `7bfd3ce` | FAIL | **B8** validator read provenance and notes in different snapshots · **M2/M7** upgrade path: deleted schema-4 sessions and missing decoded hashes · m9 repeated finalize → HTTP 500 | `95f0346`: single read snapshot + post-run re-check; `provenance_baseline` (validate refuses upgraded DBs); `seen_audio` backfilled from events; idempotent finalize |
| 3 | `95f0346` | FAIL | **M1** `validate` produced model output without recording exposure · **M2** app showed eligibility in upgraded DBs · notes: non-atomic fresh init, duplicate audit event | `9ec8e23`: `validate` records exposure before running engines; eligibility requires a `complete` baseline everywhere (fail closed by default); atomic fresh init |
| 4 | `9ec8e23` | FAIL | **M1** exposure through a copy (same samples, different container) did not reach the original | `83c87a2`: exposure and contamination follow audio identity across sessions; tombstones store both hashes |
| 5 | `83c87a2` | **PASS** | m1 duplicate upload tombstoned the shared hash, excluding a clean original in validation only | `335000d`: duplicates don't tombstone |
| 6 | `335000d` | **PASS** | m1 retained finalized copy: app vs validation disagreed on the original | `16c3404`: shared live audio makes a recording ineligible in app and validate alike |
| 7 | `16c3404` | **PASS** | **none** ("There are no remaining blocking, major or minor findings.") | – |

(B = blocking, M = major, m = minor.) Every fix added regression tests, and each new test was confirmed to fail on the
previous commit before being accepted.

CI (ubuntu-24.04, all jobs passed): 9ec8e23 → 38297415628 · 83c87a2 → 38319202236 · 335000d → 38319703477 ·
16c3404 → 38320342855 (backend 92, gate 19, docs consistency, frontend 44, Playwright 10).

Remaining risks (documented in the protocol, "Contamination tracking → Limits"; out of scope by design):
- editing the SQLite file with an external tool (for example, dropping triggers);
- fabricating browser capture metadata for re-encoded audio;
- hearing model output outside JamRecall;
- wiping the data directory.

Holdout data must be recorded in a freshly created data directory (`var-validation/`). Upgraded databases are refused.

Tech-lead disposition:
