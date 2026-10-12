# DR-0004 — May reference annotations be seeded from model output?
Status: **Approved** — Option A (tech lead, 2026-10-09)
Owner: Claude Code (implementation engineer)
Date: 2026-10-09

## Context and constraints
The tech lead's manual workflow (2026-10-09) corrects Basic Pitch output into reference notes.
The approved validation protocol says references "must never be derived from either engine's
output". Seeding from Basic Pitch lets the annotator accept its timing and pitch whenever they are
"close enough", which tends to favour Basic Pitch in the gate. It biases the comparison with pYIN in
the same direction. Correcting a draft is faster than annotating from scratch.

## Option A — seeding allowed for dev and exploratory takes; holdout must start blank (recommended; implemented)
The app records each annotation's seed (`blank` or `transcription:<id>:<engine>@<version>`), warns when a
holdout reference is model-seeded, and `jamrecall_bench.real` excludes such references from holdout
scoring and minimum counts. Cost: slower holdout annotation. Keeps the gate independent.

## Option B — seeding allowed everywhere, provenance reported
Faster, but the holdout result is not independent evidence for Basic Pitch.

## Option C — seeding forbidden everywhere
Strictest; slowest; dev annotation gains nothing in independence, since dev is used only for tuning.

## Measured evidence
None yet (no real recordings). E2E `annotation.spec.ts` verifies seed provenance, the holdout warning,
and (via the tooling dry run) the exclusion from holdout scoring.

## Recommendation and rationale
Option A. It matches the protocol already approved and keeps dev annotation fast.

## Cost, risk, reversibility
Fully reversible: provenance is stored, so references can be re-scored under another rule.

## Decision needed from tech lead
Confirm Option A, or choose B/C.

## Decision and date (leave blank pending approval)
2026-10-09, tech lead: **Option A approved.** Holdout reference annotations must start blank, without
exposure to model-generated notes. Development and exploratory annotations may be initialised from
model predictions. Preserve the independence of holdout evaluation. Document how references are
finalized, how contamination is prevented, and how changes to finalized holdout references are handled.

Documented in `docs/research/real-recording-validation-protocol.md` ("Independence of holdout
references") and `docs/testing/manual-testing-guide.md` §7.2–7.6.

Contamination guard: **approved 2026-10-12 and implemented**. Transcription requested before
finalization, or reopening after model output was requested, permanently disqualifies a recording as
holdout; so do re-uploads of audio seen before and any recording not made with the in-app recorder. The
state is write-once and trigger-enforced in the database, and recorded in exports. The gate
(`real validate`) reads references and provenance only from the database and fails closed.
Details: protocol, "Contamination tracking".
