# DR-0002 — Licensing review: PyAV / bundled FFmpeg
Status: Open — review requested; **not blocking local M1 development** (tech lead, 2026-10-09)
Owner: Claude Code (implementation engineer); reviewer: tech lead / legal
Date: 2026-10-09

## Context and constraints
The backend decodes uploaded recordings (Opus/WebM, Ogg, AAC/MP4, WAV) with `av==19.0.1` (PyAV) so no
system ffmpeg is needed. Findings on this machine (macOS x86_64 wheel):
- PyAV's own code: BSD-3-Clause (package metadata).
- Bundled `libavcodec` reports `avcodec_license()` = "LGPL version 3 or later".
- The same build's configuration includes `--enable-libx264 --enable-libx265`, and the wheel ships
  `libx264` and `libx265` dylibs. Both are GPL-licensed video encoders that JamRecall never uses.
The mix of an LGPL-reported FFmpeg with GPL encoder libraries needs review before JamRecall is
distributed in any form (binaries, containers, installers). Local development and use are unaffected.

## Option A
Keep PyAV wheels for development; before distribution, replace with an LGPL-only FFmpeg build
(audio-only codecs) or a custom PyAV build.

## Option B
Avoid server-side decoding of compressed audio: browser uploads both the original container and a
browser-decoded WAV (via `decodeAudioData`); the server reads WAV with a permissive library.
Changes the "server measures duration from the original" design.

## Option C (optional)
Depend on a system/package-manager FFmpeg (LGPL build) instead of bundled wheels.

## Measured evidence
`avcodec_license()` and `avcodec_configuration()` queried from the installed wheel via ctypes;
`av-19.0.1.dist-info/licenses/LICENSE.txt` (BSD-3-Clause); `.dylibs/` listing includes
`libx264.165.dylib` and `libx265.217.dylib`.

## Recommendation and rationale
No change during M1 (local only, no distribution). Before any distribution milestone, decide between
A and C with legal review; B only if decoding must be removed from the server.

## Cost, risk, reversibility
Decoding is isolated in `backend/jamrecall/audio.py`; swapping the decoder is low effort and reversible.

## Decision needed from tech lead
Confirm the licensing review owner and the milestone by which it must be resolved.

## Decision and date (leave blank pending approval)
