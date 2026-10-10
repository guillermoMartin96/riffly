# Decision register

| ID | Title | Status | Decided | Notes |
|---|---|---|---|---|
| [DR-0001](requests/DR-0001-transcription-engine.md) | Production transcription engine | **Approved provisionally**: Basic Pitch 0.4.0 (ONNX); pYIN benchmark-only | 2026-10-09 | Engine labelled *provisional* until the real-guitar gate passes. Gate thresholds (aggregate onset F1 ≥ 0.80, Basic Pitch ≥ pYIN; per condition A/B/C onset F1 ≥ 0.70 and ≥ 90% exact pitch) approved provisionally |
| [DR-0002](requests/DR-0002-pyav-ffmpeg-licensing.md) | Licensing: PyAV/FFmpeg and native libraries | **Open**, non-blocking for local M1 | owner assigned 2026-10-09 | Claude owns the technical investigation; legal approval is separate; must be resolved before public deployment |
| [DR-0003](requests/DR-0003-retention-and-corrections.md) | Retention of recordings and transcription outputs | **Approved** (Option A) | 2026-10-09 | Local, indefinite retention with user deletion; corrections stored separately |
| [DR-0004](requests/DR-0004-reference-seeding.md) | Seeding of reference annotations | **Approved** (Option A) | 2026-10-09 | Holdout: blank, no exposure to model notes; dev/exploratory may be model-seeded. Detection guard for pre-annotation exposure proposed, not implemented |

Reviews: [`docs/reviews/2026-10-09-codex-interim.md`](../reviews/2026-10-09-codex-interim.md), interim Codex review,
10/10 findings closed and signed off 2026-10-09.

Rule: changing the approved evaluation thresholds, tolerances or dataset requirements requires a new
decision request (`requests/TEMPLATE.md`).
