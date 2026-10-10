# Real-recording validation protocol (DR-0001 decision 2)

Status: **defined before any recording was evaluated** (2026-10-09). Thresholds approved provisionally
by the tech lead on 2026-10-09. Changing criteria, tolerances or splits after scoring the holdout requires
a new decision request.

## Purpose
Basic Pitch's GuitarSet scores are inflated by training-data overlap, so the transcription engine stays
"provisional" until it passes this test: new guitar performances, captured through JamRecall's
browser microphone path and scored against independent reference notes.

## Recording set
New performances by the tech lead, recorded for this purpose. That makes them independent of every
public dataset, including Basic Pitch's training data. No dataset audio may be used.

| Condition | Content | Gating | Minimum (dev / holdout) |
|---|---|---|---|
| A. Clean acoustic, single-note melodies | moderate tempo, scales, simple melodies, some rests and repeated notes | yes | 2 / 3 recordings, ≥ 60 holdout notes |
| B. Fast riffs and wide pitch jumps | 16th-note runs ≥ 120 bpm, leaps ≥ an octave; acoustic or clean electric | yes | 2 / 3 recordings, ≥ 60 holdout notes |
| C. Clean electric guitar | amp or DI, clean tone, single-note lines | yes | 2 / 3 recordings, ≥ 60 holdout notes |
| D. Distorted electric guitar | overdrive/distortion, single-note lines | **exploratory, not an M1 blocker** | 1 / 2 recordings |

Each recording is 10–60 s and played monophonically (single notes; chords are out of scope). Before
any scoring, recordings are assigned to dev or holdout in the reference file and never move afterwards.

Capture: JamRecall in desktop Chrome (record the browser version, OS, microphone/interface, guitar,
amp/tone, and room), with default app settings. The app disables echo cancellation, noise
suppression and auto-gain. The original upload stays in `var/`. Reference files identify the audio by
session id **and sha256**, and scoring refuses audio whose hash differs.

## Reference notes (ground truth)
One JSON file per recording in `bench/real/references/<name>.json`:

```json
{"format": "jamrecall-reference-v1", "session_id": "…", "audio_sha256": "…",
 "status": "final", "seed": "blank", "revision": 1,
 "split": "dev|holdout", "condition": "A|B|C|D", "method": "manual|score",
 "annotator": "…", "instrument": "…", "notes_text": "…",
 "notes": [{"start": 0.512, "end": 0.903, "midi": 64, "technique": null}]}
```
`status` (must be `final`) and `seed` (`blank` or `transcription:<id>:<engine>@<version>`) are
**required**; nothing is inferred. Each recording (session id and audio hash) may appear only once
across all references. Notes must lie within the recording. `prepare` writes no manifest if any
reference fails these checks.

References are made in JamRecall's **Reference annotation** panel (or as JSON in the same format) and
exported with `python -m jamrecall.manage export-references --out bench/real/references`. Only
**finalized** annotations are exported or scored. **Holdout** references must not be derived from either
engine's output: start them blank. Dev and exploratory references may be started from model output.
The seed is recorded, and the scorer excludes model-seeded holdout references (DR-0004 asks the tech lead
to confirm this rule).
- **manual**: annotate each played note on the original audio with the in-app editor (zoom the timeline,
  set the playhead, listen to single notes, nudge in 10 ms steps); external tools such as Sonic
  Visualiser are also fine. Onset = start of the attack transient; pitch = fretted note
  (A4 = 440 Hz equal temperament); end = when the note is stopped, or the next note's onset for
  legato, or when it is no longer audible. A second listening pass checks every note.
- **score**: play a pre-written phrase (pitches known from its tab or MIDI) to a click after a count-in.
  Pitches come from the score; onsets start on the click grid and **must then be corrected by hand
  to the actual attacks**, because human timing routinely deviates by more than 50 ms.

Techniques: notes played with a bend, slide, hammer-on/pull-off, vibrato or harmonic get a `technique`
tag (pitch = the note at its onset). They are included in the main score and also reported separately.

## Scoring (identical to the benchmark, `bench/jamrecall_bench/score.py`)
- Matching: mir_eval, onset ±50 ms, pitch ±50 cents (exact MIDI note); offset-aware matching also
  requires the end within max(50 ms, 20% of reference duration). Micro-averaged over notes.
- Reported **per recording, per condition and in aggregate**:
  - onset precision / recall / F1;
  - pitch correctness: exact-pitch rate and octave-error rate among onset-matched notes;
  - note-end quality: offset-aware F1 and median absolute end error;
  - latency: inference time and real-time factor per recording, plus end-to-end UI latency (E2E).
- Engines: the app's Basic Pitch configuration (`BasicPitchAdapter`, parameters frozen as in
  `bench/results/basic-pitch.json`) and the pYIN baseline (`bench/results/pyin.json`).
  Audio is decoded with the app's own decoder (`jamrecall.audio.decode_mono`, 22,050 Hz mono).
- **No tuning on holdout.** Parameters may be re-tuned only on the real **dev** split
  (`real.py score --tune-on-dev`). The gate only passes for the parameters the app actually runs
  (`backend/jamrecall/transcription/basic_pitch_params.json`). A result tuned on dev therefore reports
  INCOMPLETE until the new parameters are approved, integrated into the app, and the untuned app
  configuration is re-scored.
- **Bound evidence**: the manifest carries a content fingerprint. Both engines' results must have been
  scored on exactly that manifest (same fingerprint and recording ids), with a holdout summary for every
  gating condition; otherwise the gate reports INCOMPLETE.

## Pass criteria
Gate (approved by the tech lead, 2026-10-09), on the **holdout** recordings of conditions A+B+C combined:
1. Basic Pitch onset F1 ≥ 0.80, and
2. Basic Pitch onset F1 ≥ pYIN onset F1 on the same recordings, and
3. for **each** gating condition A, B, C (provisionally approved 2026-10-09): Basic Pitch holdout onset
   F1 ≥ 0.70 **and** ≥ 90% of onset-matched notes have the correct MIDI pitch.

Reported separately for every recording, condition and aggregate: precision, recall, pitch accuracy,
and note-end accuracy (offset-aware F1 and median end error). The gate is INCOMPLETE while any gating
condition is below its minimum recording or note count.
Condition D is reported but never gates M1.

If the gate fails or a gating condition performs poorly: **stop**, raise a decision request with the
evidence and options, and do not loosen these thresholds.

## Procedure
```sh
# 1. record in JamRecall; write references in bench/real/references/ (split fixed up front)
# (from bench/)
# 2. decode with the app's pipeline, verify hashes, build the "real" corpus
../backend/.venv/bin/python -m jamrecall_bench.real prepare --data-dir ../var
# 3. score both engines (frozen params); optional dev-only re-tuning
.venv-bp/bin/python   -m jamrecall_bench.real score basic-pitch
.venv-pyin/bin/python -m jamrecall_bench.real score pyin
# 4. evaluate the gate -> bench/results/real-gate.json
.venv-pyin/bin/python -m jamrecall_bench.real gate
```
Run the commands from `bench/`. `prepare` uses the backend venv so it decodes with the app's own code. The recordings
themselves are not committed (privacy). The reference JSON files and result files are committed.
