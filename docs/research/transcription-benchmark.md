# Transcription benchmark — results (gate C, M1)

Date: 2026-10-09 · Branch: `feature/m1-audio-riff-slice` · Protocol: `transcription-evaluation.md`
Reproduction: `bench/README.md` · Generated tables: `bench/results/summary.md` · Raw results:
`bench/results/*.json`. Every number below is copied from those files; nothing was estimated.

## Candidates

| | pYIN + onset segmentation | Basic Pitch 0.4.0 (ICASSP-2022 model, ONNX) |
|---|---|---|
| Type | Classical: probabilistic YIN f0 + voicing (librosa 1.0.0), notes = runs of stable rounded pitch split at spectral-flux onsets | Neural audio-to-MIDI (Spotify), note/onset posteriorgrams → notes; we add a one-note-at-a-time post-process |
| Licence | librosa ISC; numba/llvmlite BSD | Apache-2.0 (code and bundled model); onnxruntime MIT |
| Install on this machine (macOS 26.2 x86_64, Py 3.12.15) | Clean: `pip install -r bench/requirements-pyin.txt` | **Deviation**: package metadata requires `tensorflow-macos<2.15.1` on macOS + Python > 3.11, which has no wheels. Works with `--no-deps` + pinned deps + bundled `nmp.onnx` (see "Installation deviations") |
| Venv size | 381 MB | 551 MB |
| Maintenance | librosa actively released (1.0.0) | Last release 0.4.0 (Aug 2024) |

Also scored: the backend's **TEST-ONLY fixture** (ignores audio) as a floor, to show the metrics separate
fixture output from real predictions. aubio was not evaluated (no binary wheel; needs a compiler).

## Corpora

1. **GuitarSet v1.1.0** — real acoustic guitar, reference-mic audio, note annotations from a hexaphonic
   pickup with manual correction. CC BY 4.0, doi:10.5281/zenodo.3371780 (md5-verified downloads).
   Consent: recorded and released by the dataset authors (Xi et al., ISMIR 2018) under CC BY 4.0;
   no new people were recorded. From the 180 solo excerpts we cut **monophonic segments** (no note overlap
   > 30 ms; crops exclude any other sounding annotated note): dev = players 00–02 (502 segments, 29.3 min,
   5,610 notes), holdout = players 03–05 (365 segments, 38.5 min, 6,119 notes).
2. **Synthetic** — Karplus-Strong plucked string, **not guitar**, exact labels: single notes (low/mid/high),
   ascending/descending scales, pentatonic with rests, repeated same-pitch notes, wide leaps, 16th-note
   riff; 70/110/150 bpm; clean / 20 dB noise / reverb. 252 clips, 12.8 min, 1,800 notes; dev and holdout
   use different seeds and transpositions.

## Results (holdout; parameters selected on GuitarSet dev only)

| Method | GuitarSet onset P / R / F1 | +offset F1 | median onset err | pitch exact (onset-matched) | Synthetic onset F1 | +offset F1 |
|---|---|---|---|---|---|---|
| pYIN + onsets | 0.786 / 0.856 / **0.820** | 0.687 | 12.0 ms | 97.2% | **0.839** | 0.696 |
| Basic Pitch, mono post-process | 0.883 / 0.931 / **0.906** ⚠ | 0.789 ⚠ | 8.2 ms | 97.8% | **0.994** | 0.873 |
| Basic Pitch, raw polyphonic | 0.842 / 0.932 / 0.885 ⚠ | 0.768 ⚠ | 8.3 ms | 96.9% | 0.965 | 0.770 |
| TEST-ONLY fixture | 0.003 / 0.002 / 0.002 | 0.000 | – | – | 0.004 | 0.004 |

Tolerances: onset ±50 ms, pitch ±50 cents; offset-aware additionally max(50 ms, 20% of note). Dev and
holdout scores are within 0.01 F1 for every method on GuitarSet.

⚠ **Training-data contamination.** The Basic Pitch paper (Bittner et al., ICASSP 2022, Table 1) lists
GuitarSet among its training sets (648 train / 72 test tracks); the split by player is not given. Our
GuitarSet holdout was very likely seen in training, so **Basic Pitch's GuitarSet scores are an
optimistic upper bound and are not evidence of generalisation**. pYIN has no training data, though its
segmentation parameters were tuned on GuitarSet dev. The synthetic corpus is uncontaminated for both.

Where the methods differ most (synthetic holdout onset F1, pYIN → Basic Pitch mono): 16th-note riff
0.600 → 0.992; wide leaps 0.580 → 0.983; 150 bpm 0.782 → 0.997. pYIN is competitive on slow scales,
repeated notes and single notes. Noise and reverb barely affect either method on synthetic audio.
Basic Pitch's mono post-process beats its raw polyphonic output on precision (0.883 vs 0.842).

## Runtime and memory (fresh process, 6 whole holdout solos, 157 s of audio)

| | import + model load | first call (22.3 s audio) | warm real-time factor | CPU-s per wall-s | peak RSS |
|---|---|---|---|---|---|
| pYIN | 0.01 s (lazy imports) | 11.0 s (numba JIT compile) | 0.081 | 0.98 | 653 MB |
| Basic Pitch (ONNX) | 2.19 s | 0.53 s | 0.0118 | 6.97 | 309 MB |

Basic Pitch's lower latency comes from multithreading in ONNX Runtime. **Total CPU per audio second is
about the same** (≈0.082 vs ≈0.079 CPU-s). Basic Pitch uses about half the memory. Neither is real-time
streaming; both process a finished take in well under its duration on this machine.

## Installation deviations (Basic Pitch) and clean-install test

Deviations from the standard `pip install basic-pitch`:
1. `basic-pitch==0.4.0` installed with `--no-deps` (its Darwin markers require `tensorflow-macos` and
   `coremltools`; neither is used by the ONNX backend and `tensorflow-macos` has no Python 3.12 wheel).
2. ONNX backend: `onnxruntime==1.23.2`, model `basic_pitch/saved_models/icassp_2022/nmp.onnx` from the wheel.
3. `resampy==0.4.2` (basic-pitch requires `<0.4.3`), which imports `pkg_resources` → `setuptools<81` (80.10.2).
4. Every package pinned in `bench/requirements-basicpitch.lock` (43 lines, `pip freeze` of the benchmark venv).

`sh bench/clean_install_test.sh` (2026-10-09, macOS 26.2 x86_64, Python 3.12.15): new venv in a temp
dir, `--no-cache-dir`, binary wheels only → `pip check` reports only the two unused declared deps above;
smoke clip pitches `[54, 56, 58, 59, 61, 63, 65, 66]` match the reference exactly; **20/20 holdout clips
produce identical notes to the benchmark venv** → **PASS** (152 s wall incl. downloads). Not yet run on
Linux; CI will exercise the install once the adapter is integrated.

## After DR-0001
Basic Pitch is integrated in the app with these parameters. `backend/tests/test_basic_pitch.py` checks
that the app adapter reproduces this benchmark's notes exactly. The real-recording gate that
compensates for the GuitarSet overlap is defined in `real-recording-validation-protocol.md`.

## Failure cases and limitations

- pYIN misses fast notes (late voicing at onsets, `min_note_s` = 0.1 s) and merges leaps; Basic Pitch's
  raw output adds spurious simultaneous notes (sympathetic strings, harmonics) that mono post-processing removes.
- Octave errors are rare for both (≤ 0.5% of onset-matched notes in mono mode).
- **No electric-guitar recordings** in either corpus (GuitarSet is acoustic only; synthetic is not guitar).
- **No recordings captured through JamRecall's browser path** (MediaRecorder Opus/WebM, browser mic,
  untreated room). Opus compression and laptop microphones are untested.
- Bends, slides, vibrato, harmonics, palm mutes and chords are not modelled by the note schema.
- GuitarSet contamination for Basic Pitch (above).
- Single machine (Intel x86_64 macOS); runtimes will differ elsewhere.
