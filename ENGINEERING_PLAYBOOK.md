# JamRecall engineering playbook

## Principles
1. Deliver executable vertical slices, not scaffolding alone.
2. Preserve original audio and immutable source timestamps; riff ranges reference source sessions.
3. Canonical notes are independent of model, notation renderer, and inferred guitar fingering.
4. Keep inference replaceable through a versioned adapter and normalized event schema.
5. Treat fret/string selection as inferred and editable, not observed fact.
6. Keep recording local to the development environment by default; document upload and retention behavior.
7. No camera, accounts, cloud deployment, live streaming inference, chords, or generative AI in M1.
8. Test browser permission denial, empty recording, failed inference, missing media, bad range, and reload persistence.

## Branch and PR protocol
- Create `feature/m1-audio-riff-slice` from main; never directly edit main.
- Make small coherent commits and push when configured. Final commits must pass checks.
- Open PR to main; include summary, changed files, evidence, limitations, risk, and rollback.
- Request independent Codex review; resolve blocking findings, rerun tests, and record findings in docs/reviews.
- Do not merge or begin M2 without explicit tech-lead approval.

## Decision requests
Use docs/decisions/requests/TEMPLATE.md for material tradeoffs. Recommend an option, explain alternatives, cost, reversibility, and required approval. Do not self-approve.

## Research gates
Benchmark at least two credible methods against the same labeled monophonic guitar dataset before choosing a production transcription engine. Compare accuracy, timing, latency, compatibility, license, and resource cost. A deterministic fixture adapter is allowed only for UI/integration tests and must be labeled test-only.

## Proof
Maintain reproducible scripts/commands, dataset provenance, benchmark tables, browser screenshots, and known failures. Do not fabricate measurements. No unverified success claims.
