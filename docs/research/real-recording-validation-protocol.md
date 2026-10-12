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
References are made in JamRecall's **Reference annotation** panel and live in the app database
(`annotations`, `annotation_notes`). **The database is the only input the gate uses**: the gate
reads every finalized reference directly from it. The exported files (`reference.json` in a session
export, or `python -m jamrecall.manage export-references --out bench/real/references`) are archival
copies in this format:

```json
{"format": "jamrecall-reference-v1", "session_id": "…", "audio_sha256": "…",
 "status": "final", "seed": "blank", "revision": 1,
 "split": "dev|holdout", "condition": "A|B|C|D", "method": "manual|score",
 "annotator": "…", "instrument": "…", "notes_text": "…", "provenance": {"…": "…"},
 "notes": [{"start": 0.512, "end": 0.903, "midi": 64, "technique": null}]}
```
Editing an exported file has no effect on validation.

### Independence of holdout references (DR-0004, approved 2026-10-09)
- **Holdout** references start **blank**, and the annotator has **no exposure to model-generated notes**
  for that take before finalizing: the take is not transcribed until its reference is finalized.
- **Dev** and exploratory references may be started from model output (`seed` =
  `transcription:<id>:<engine>@<version>`).
- Enforcement: the seed is stored with every annotation; the UI warns when a holdout reference is
  model-seeded; the gate excludes model-seeded holdout references. The contamination guard below
  covers exposure.
- **Finalization**: requires split, condition and annotator, plus at least one note, and locks the
  split permanently. A finalized reference cannot be changed without **Reopen**; database triggers
  enforce this.
- **Changes after finalization**: **Reopen** keeps the split locked and increments the revision.
  - Reopening after model output was requested for the take contaminates it permanently (the app
    warns first).
  - Before any holdout validation run, a correction to an unexposed holdout reference is allowed;
    the reason goes in the Notes field.
  - After holdout validation has been run, holdout references are frozen. A correction needs a new
    decision request recording the reason and the before/after scores.
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

## Contamination tracking (DR-0004 guard, approved 2026-10-12)
The app database is the only source of truth for holdout eligibility (`jamrecall.provenance`).
- **Eligible** only when all of these hold:
  - recorded with the in-app recorder (browser capture metadata, recorder container) and tracked
    from the moment it was created (`provenance_origin = recorded`);
  - never contaminated.

  Imported files and recordings that existed before tracking (*pre-tracking*) are never eligible.
- **Contaminated (permanent)** when any of these happens:
  - a transcription is *requested* while the recording has no finalized annotation (requesting is
    the earliest point at which model output can exist or be seen; failed runs count too);
  - a finalized annotation is *reopened* after a transcription was requested;
  - its audio was uploaded before, in any session, even a deleted one. Both the container hash and
    the decoded-audio hash are checked, so re-wrapping the same samples doesn't help
    (`seen_audio`, `contaminated_audio`);
  - it was transcribed before tracking existed (*uncertain*).
- **Enforced in the database**, not just in application code:
  - every request runs in a `BEGIN IMMEDIATE` transaction with freshly read state;
  - SQLite triggers make the provenance fields write-once, `provenance_events` append-only, and
    `seen_audio` / `contaminated_audio` permanent;
  - triggers refuse a transcription row unless exposure (and, if unfinalized, contamination) was
    recorded first, refuse reopening an exposed reference unless contamination was recorded first,
    and refuse changes to a finalized reference or its notes;
  - so concurrent requests, changing split or metadata, deleting transcription rows, re-exporting or
    restarting the app cannot clear or skip it.
- **User experience**:
  - Before an action that would disqualify a still-eligible recording (Transcribe before
    finalization, Reopen after model output was requested), the API refuses with
    `409 would_disqualify_holdout`.
  - The UI then explains the consequence and offers **Cancel** or **Continue anyway**; continuing
    is recorded. Transcription after finalization needs no confirmation.
  - Every recording shows a *Holdout-eligible* / *Not holdout-eligible (reason)* badge.
- **Exports**: `metadata.json` contains `provenance` plus the full event log, and `reference.json`
  contains an informational copy. The gate trusts neither.
- **Gate (fails closed)**, in `validate`:
  - Eligibility comes from the same `provenance.status` function the app uses, applied to the
    database rows, plus dataset checks: engine seed; model output requested before the latest
    finalization; the same audio (container or decoded) more than once in the dataset.
  - Excluded holdout recordings are listed with their reasons in `excluded_holdout`. They never count
    toward holdout scores, minimum takes or minimum notes.
  - The verdict is INCOMPLETE when any of these is found: a missing or pre-tracking database; a
    missing or changed original recording; decoded audio differing from the hash stored at upload;
    reference notes past the end of the audio.
  - Dev and exploratory recordings may be contaminated without consequence.
- **Limits**:
  - The guard covers mistakes, concurrency and manipulation through the app, exported files and the
    gate's inputs.
  - Out of scope for a local single-user app: deliberately editing the SQLite file with a separate
    tool (dropping the triggers), fabricating browser capture metadata for re-encoded audio
    (different samples, so different hashes), and listening to model output outside JamRecall.
  - Wiping `var/` erases provenance. Don't wipe a data directory that holds a validation dataset.

## Scoring (identical to the benchmark, `bench/jamrecall_bench/score.py`)
- Matching: mir_eval, onset ±50 ms, pitch ±50 cents (exact MIDI note); offset-aware matching also
  requires the end within max(50 ms, 20% of reference duration). Micro-averaged over notes.
- Reported **per recording, per condition and in aggregate**:
  - onset precision / recall / F1;
  - pitch correctness: exact-pitch rate and octave-error rate among onset-matched notes;
  - note-end quality: offset-aware F1 and median absolute end error;
  - latency: inference time and real-time factor per recording, plus end-to-end UI latency (E2E).
- Engines: the app's Basic Pitch configuration (parameters from
  `backend/jamrecall/transcription/basic_pitch_params.json`, which equals the GuitarSet-dev selection in
  `bench/results/basic-pitch.json`), and the pYIN baseline (`bench/results/pyin.json`).
  Audio is decoded with the app's own decoder (`jamrecall.audio.decode_mono`, 22,050 Hz mono).
- **One process, no trusted intermediates**: `validate` reads the database, checks each original
  recording against its stored container and decoded-audio hashes, runs both engines on that audio,
  scores, and decides in a single run. It never reads score, manifest or reference files back. The
  report records a dataset fingerprint (ids, splits, seeds, revisions, notes, audio hashes) for the
  record.
- **No tuning on holdout.** `tune-dev` reports the best parameters on the real **dev** split for
  information only. `validate` always uses the app's own parameters, so adopting tuned parameters
  requires a decision request and an app change, then a fresh validation.

## Pass criteria
Gate (approved by the tech lead, 2026-10-09), on the **holdout** recordings of conditions A+B+C combined:
1. Basic Pitch onset F1 ≥ 0.80, and
2. Basic Pitch onset F1 ≥ pYIN onset F1 on the same recordings, and
3. for **each** gating condition A, B, C (provisionally approved 2026-10-09): Basic Pitch holdout onset
   F1 ≥ 0.70 **and** ≥ 90% of onset-matched notes have the correct MIDI pitch.

Verdicts (`bench/results/real-validation.json`, exit code 0/1/2):
- **PASS**: all checks 1–3 hold, with complete, verified evidence.
- **FAIL**: the evidence is complete, but at least one check fails. A failing gating condition is
  listed in `poor_conditions`.
- **INCOMPLETE**: any gating condition is below its minimum recording or note count (after
  exclusions), a summary is missing, or an integrity problem was found (`integrity_problems`). No
  conclusion is drawn.

Reported separately for every recording, condition and aggregate: precision, recall, pitch accuracy,
and note-end accuracy (offset-aware F1 and median end error).
Condition D is reported but never gates M1.

If the gate fails or a gating condition performs poorly: **stop**, raise a decision request with the
evidence and options, and do not loosen these thresholds.

## Procedure
```sh
# 1. record and annotate in JamRecall (docs/testing/manual-testing-guide.md §7); finalize every take
# 2. from bench/, with the backend venv (app decoder, Basic Pitch, librosa, mir_eval):
../backend/.venv/bin/python -m jamrecall_bench.real validate --data-dir ../var
#    -> prints the verdict, exclusions and scores; writes bench/results/real-validation.json
# optional, informational only:
../backend/.venv/bin/python -m jamrecall_bench.real tune-dev --data-dir ../var
# archival copy of the finalized references (not used by the gate):
../backend/.venv/bin/python -m jamrecall.manage export-references --out real/references
```
The recordings are not committed (privacy). The validation report and archival reference JSON files
are committed.
