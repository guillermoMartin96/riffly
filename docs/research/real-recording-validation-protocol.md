# Real-recording validation protocol (DR-0001 decision 2)

Status: **defined before any recording was evaluated** (2026-10-09). Thresholds approved provisionally
and DR-0004 (reference seeding) approved by the tech lead on 2026-10-09. **Changing thresholds, tolerances,
dataset minimums or splits requires a new decision request.** Step-by-step collection instructions:
`docs/testing/manual-testing-guide.md` §7.

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

Each recording is 10–60 s and played monophonically (single notes; chords are out of scope).
Each is an independent performance in its own JamRecall session. The same session or audio may not
appear twice anywhere in the dataset, and exploratory takes are not reused. The split of every take is
decided **before it is played**, recorded in its reference, locked at finalization, and never changed.
Minimum for the gating conditions: **15 takes** (A, B, C × 2 dev + 3 holdout).

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
**finalized** annotations are exported or scored.

### Independence of holdout references (DR-0004, approved 2026-10-09)
- **Holdout** references start **blank**, and the annotator has **no exposure to model-generated notes**
  for that take before finalizing: the take is not transcribed (no **Transcribe**, no viewing of its
  transcriptions or export) until its reference is finalized.
- **Dev** and exploratory references may be started from model output (`seed` =
  `transcription:<id>:<engine>@<version>`).
- Enforcement:
  - The seed is stored with every annotation, and the UI warns when a holdout reference is
    model-seeded.
  - `prepare` requires an explicit seed; `score` and `gate` exclude model-seeded holdout references
    from scoring and from the minimum counts.
  - **Not detectable today**: a holdout take that was transcribed and viewed *before* blank annotation.
    That relies on the procedure above. Such a take must not be finalized as holdout; it is deleted or
    used as dev, and a replacement holdout take is recorded.
- **Finalization**: requires split, condition and annotator, plus at least one note, and locks the
  split permanently.
- **Changes after finalization**: **Reopen** keeps the split locked and increments the revision. Both
  are in the dataset fingerprint, so earlier scores become stale (gate INCOMPLETE until re-scored).
  - Before any holdout scoring, a correction is allowed if the annotator has not seen model output
    for the take; the reason goes in the Notes field.
  - After holdout scoring has started, holdout references are frozen. A correction needs a new
    decision request recording the reason and the before/after scores.
  - A holdout reference reopened after its take was transcribed is contaminated: it is excluded
    (delete the take) and replaced.
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
- Engines: the app's Basic Pitch configuration (`BasicPitchAdapter`, parameters from
  `backend/jamrecall/transcription/basic_pitch_params.json`, which equals the GuitarSet-dev selection in
  `bench/results/basic-pitch.json`), and the pYIN baseline (`bench/results/pyin.json`).
  Audio is decoded with the app's own decoder (`jamrecall.audio.decode_mono`, 22,050 Hz mono).
- **No tuning on holdout.** Parameters may be re-tuned only on the real **dev** split
  (`real.py score --tune-on-dev`). The gate only passes for the parameters the app actually runs
  (`backend/jamrecall/transcription/basic_pitch_params.json`). A result tuned on dev therefore reports
  INCOMPLETE until the new parameters are approved, integrated into the app, and the untuned app
  configuration is re-scored.
- **Dataset fingerprint**: `prepare` writes a manifest with a SHA-256 fingerprint covering every
  recording's id, split, condition, seed, revision, reference notes, original-audio hash, analysis-audio
  path and analysis-audio hash.
  - `score` refuses analysis audio that changed after `prepare`, and records the fingerprint and the
    recording ids it scored.
  - The gate reports INCOMPLETE unless both engines' results carry exactly the current fingerprint and
    ids, include a holdout summary for every gating condition, and Basic Pitch was scored with the
    app's full parameter set (untuned).

## Pass criteria
Gate (approved by the tech lead, 2026-10-09), on the **holdout** recordings of conditions A+B+C combined:
1. Basic Pitch onset F1 ≥ 0.80, and
2. Basic Pitch onset F1 ≥ pYIN onset F1 on the same recordings, and
3. for **each** gating condition A, B, C (provisionally approved 2026-10-09): Basic Pitch holdout onset
   F1 ≥ 0.70 **and** ≥ 90% of onset-matched notes have the correct MIDI pitch.

Verdicts (`bench/results/real-gate.json`, exit code 0/1/2):
- **PASS**: all checks 1–3 hold, with complete and untampered evidence.
- **FAIL**: the evidence is complete, but at least one check fails. A failing gating condition is
  listed in `poor_conditions`.
- **INCOMPLETE**: any gating condition is below its minimum recording or note count, a summary is
  missing, or the evidence is stale or mismatched (`integrity_problems`). No conclusion is drawn.

Reported separately for every recording, condition and aggregate: precision, recall, pitch accuracy,
and note-end accuracy (offset-aware F1 and median end error).
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
