# Assumptions log

Assumptions made during M1 that a reviewer may want to challenge. Each one says how it is checked or what would invalidate it.

| # | Assumption | Basis / check | Invalidated if |
|---|---|---|---|
| 1 | Supported dev environment: macOS x86_64, Python 3.12, Node ≥ 20.19; CI ubuntu-24.04 | Verified installs and CI runs | Another platform must be supported |
| 2 | Sample index 0 of the decoded buffer equals HTML `<audio>` time 0 | `decode_mono` pads to the first frame's pts; onset alignment < 50 ms tested for WAV, Opus/WebM, Opus/Ogg, AAC/MP4 (`test_basic_pitch.py`) | A browser's playback offset differs (e.g. AAC priming handled differently) |
| 3 | Server-decoded duration is canonical; the browser's `duration` may be `Infinity` for MediaRecorder WebM | Riff validation uses the server duration | – |
| 4 | Users record monophonic lines; chords are out of scope | M1 non-goals | Users mostly play chords |
| 5 | Basic Pitch parameters selected on GuitarSet dev carry over to browser-recorded audio | **Unverified**: real-recording gate (protocol doc) | Gate fails or a condition performs poorly |
| 6 | Basic Pitch's GuitarSet scores are optimistic (training overlap) | Paper Table 1 | – |
| 7 | Synthetic Karplus-Strong audio is valid for integration tests, not for accuracy claims | Labelled synthetic everywhere | – |
| 8 | Chromium's fake-capture path (Linux CI) and Web Audio injection (macOS) exercise the same MediaRecorder/upload code as a real microphone | Both modes pass the same E2E; only the capture source differs | A real microphone shows codec or sample-rate behaviour the fakes don't |
| 9 | A single local user; no auth needed | M1 scope; server binds 127.0.0.1 | Multi-user or hosted use |
| 10 | Local, indefinite retention with user deletion is acceptable for M1 | DR-0003 approved 2026-10-09 | Hosted or multi-user use |
| 11 | Licensing is acceptable for local development | DR-0002 (non-blocking) | Any distribution or public deployment |
| 12 | `typing_extensions` 4.16.0 (vs 4.15.0 in the bench lock) does not change Basic Pitch output | Parity test: identical notes to the benchmark pipeline | Parity test fails |
| 13 | The browser's `duration` for Chrome MediaRecorder WebM can be up to one Opus frame (60 ms) shorter than the server-decoded length; the start is aligned | Measured 2026-10-09: first packet pts 0, Opus pre-skip 0, last 60 ms packet at 4.977 s, decoded to 5.037 s | A take shows a start offset between playback and notes |
| 14 | Holdout references are independent of model output: blank seed (enforced) and no viewing of the take's transcription before finalizing (procedural) | DR-0004 approved 2026-10-09; seed checked by the gate | A holdout take is transcribed before its reference is finalized |
| 15 | Port 8700 (API) and 5173 (app) are free on the tech lead's Mac; port 8000 is used by another local FastAPI app | Checked 2026-10-09; `scripts/dev.sh` refuses busy ports | – |
