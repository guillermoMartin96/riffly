# DR-0002 — Licensing review: PyAV / bundled FFmpeg and other native libraries
Status: Open — review requested; **not blocking local M1 development** (tech lead, 2026-10-09).
**Must be resolved before any public deployment or distribution.**
Owner: Claude Code, technical licensing investigation and documentation (assigned by the tech lead, 2026-10-09); legal approval: counsel
Date: 2026-10-09 (updated after the Basic Pitch integration)

This is an engineering inventory, not legal advice. The obligations listed are the ones commonly
associated with each licence and must be confirmed by counsel.

## Context and constraints
JamRecall M1 runs only on the developer's machine; nothing is distributed or hosted. A public
deployment (hosted service) and a distribution (installer, container image, desktop bundle) bring
different obligations. Both are out of scope for M1.

## Findings (from installed package metadata and wheel contents, macOS x86_64, 2026-10-09)

| Component | How it is used | Licence (as reported) | Notes |
|---|---|---|---|
| PyAV 19.0.1 | decode uploads (`audio.py`) | BSD-3-Clause | wheel bundles 17 native libraries |
| FFmpeg 8.x libs (in PyAV wheel) | decoding | `avcodec_license()` = **LGPL v3+** | configuration also has `--enable-libx264 --enable-libx265` |
| libx264, libx265 (in PyAV wheel) | **unused** (video encoders) | **GPL** | GPL code shipped next to an LGPL-reported build: the main concern |
| libsndfile (in soundfile wheel) | WAV I/O in bench + Basic Pitch deps | **LGPL-2.1** | dynamic library `_soundfile_data/libsndfile_x86_64.dylib` |
| libsoxr (in `soxr` wheel, librosa dep) | resampling inside librosa | **LGPL-2.1-or-later** | compiled into `soxr_ext.abi3.so` |
| certifi | CA bundle (requests/pooch) | MPL-2.0 | file-level copyleft; unmodified use |
| Basic Pitch 0.4.0 code + model | transcription | Apache-2.0 | `LICENSE` + `NOTICE` (Spotify AB) |
| ONNX Runtime 1.23.2 | model inference | MIT | ships `ThirdPartyNotices.txt` |
| librosa, resampy | Basic Pitch deps | ISC | |
| numba, llvmlite, scipy, numpy, scikit-learn, starlette, uvicorn, soundfile (py) | runtime | BSD variants | llvmlite bundles LLVM (Apache-2.0 with LLVM exception) |
| fastapi, pydantic, onnxruntime, pretty_midi, mido | runtime | MIT | |
| protobuf, flatbuffers, python-multipart, requests | runtime | BSD-3 / Apache-2.0 | |
| React 19, react-dom, scheduler | frontend bundle | MIT | only production frontend deps |
| GuitarSet v1.1.0 | benchmark only, **not shipped** | CC BY 4.0 | attribution in any published benchmark results |

## Obligations to satisfy before public deployment / distribution
1. **GPL x264/x265**: decide whether shipping the PyAV wheel as built is acceptable. The likely fix is
   an FFmpeg/PyAV build without GPL components (audio-only decoders) or a system LGPL FFmpeg (Options
   A/C below). Confirm the licence of the bundled FFmpeg build with the PyAV maintainers.
2. **LGPL libraries (FFmpeg, libsndfile, libsoxr)**, if distributed: give the licence texts and
   notices, offer the corresponding source of those libraries, and let users replace or relink them
   (dynamic linking satisfies this for FFmpeg and libsndfile). `soxr`'s static linking needs specific review.
3. **Apache-2.0 (Basic Pitch, protobuf, …)**: include the licence and keep Basic Pitch's `NOTICE` file
   in distributed artefacts and in a "third-party notices" page.
4. **MIT/BSD/ISC**: reproduce copyright and licence notices (collect into `THIRD_PARTY_NOTICES`),
   including ONNX Runtime's `ThirdPartyNotices.txt`.
5. **MPL-2.0 (certifi)**: unmodified use; if modified, publish the modified files.
6. **Hosted service only** (no distribution): GPL/LGPL distribution duties are generally not triggered by
   network use, but counsel should confirm. The notices page is still recommended.
7. **GuitarSet CC BY 4.0**: credit Xi et al., ISMIR 2018 (doi:10.5281/zenodo.3371780) wherever benchmark
   results are published. Do not redistribute the audio without the same attribution.
8. **Basic Pitch model**: the model weights are distributed in the Apache-2.0 package. Confirm with
   counsel that no separate model or training-data terms apply.

## Options for the decoder
- **A**: keep PyAV for development; before distribution switch to an LGPL-only, audio-only FFmpeg build (custom PyAV wheel).
- **B**: remove server-side compressed-audio decoding (browser uploads the original plus a browser-decoded
  WAV). This changes the "server measures from the original" design.
- **C**: depend on a system or package-manager LGPL FFmpeg instead of bundled wheels.

## Recommendation
No change during M1. Before a deployment milestone: generate `THIRD_PARTY_NOTICES` automatically from
the lock files, choose A or C for FFmpeg with counsel, and review `soxr` linking.

## Cost, risk, reversibility
Decoding is isolated in `backend/jamrecall/audio.py`; swapping the decoder is low effort and reversible.

## Decision needed from tech lead
Name the licensing review owner and the milestone by which it must be resolved.

## Decision and date (leave blank pending approval)
2026-10-09, tech lead: review opened as non-blocking for local M1 development. Resolution required before
public deployment. Owner and deadline: pending.

2026-10-09, tech lead: Claude owns the technical investigation and documentation. Material licensing
risks must be resolved before public deployment. Unresolved legal or distribution questions go to new
decision requests. **A technical review does not replace legal approval.** Status: inventory and
obligations documented above; no legal opinion has been obtained; nothing is distributed.
