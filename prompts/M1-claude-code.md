# Claude Code — first JamRecall implementation task
You are the implementation engineer for JamRecall. First read CLAUDE.md, ENGINEERING_PLAYBOOK.md, docs/milestones/M1.md, docs/proof/M1-proof.md, and docs/research/transcription-evaluation.md. Inspect this machine's OS, available runtimes and package managers before selecting/installing versions. Do not assume modern Python is installable; avoid changing system Python.

1. Confirm the repo and current git status. Create feature/m1-audio-riff-slice from main; do not commit directly to main.
2. Write a concise execution plan in docs/milestones/M1-implementation-plan.md, including API routes, UI flows, data schema, tests, and risks. Keep it updated.
3. Implement an executable vertical slice incrementally using React/TypeScript/Vite and FastAPI/SQLite/local audio files. Begin with actual recording, persistence and playback; make sure a user can save/reload a named time-range riff. Keep timestamps referenced to original audio.
4. Define a transcription adapter contract and normalized NoteEvent schema. For early UI tests, allow a clearly labeled fixture adapter ONLY in tests/dev mode. Never present fixture notes as recognized guitar audio.
5. Research and benchmark at least two viable real transcription approaches with reproducible labeled audio and objective metrics. Verify licensing, compatibility, installation footprint and actual runtime. Write a comparison and a decision request; STOP before committing to a production inference engine and ask the tech lead to approve. If no real inference can be integrated without a decision, report the partial vertical slice as incomplete M1, not done.
6. After approval, integrate the chosen real adapter, display synchronized tablature, and test the entire recorded-audio workflow. Keep fingering estimates distinguishable from detected pitch.
7. Add automated backend/frontend tests and browser E2E tests where practical. Include error paths, data retention and riff reference semantics. Document exact commands and observed results in docs/proof/M1-proof.md.
8. Commit coherent increments and push to feature branch when remote configured. Prepare/open a PR only when complete, with actual test evidence and limitations. Request independent Codex review; do not self-approve, merge, or start M2.

At each approval gate, present: completed work, evidence, recommended choice, tradeoffs, and exact decision needed. Never fabricate benchmarks, PR URLs, screenshots or CI results.
