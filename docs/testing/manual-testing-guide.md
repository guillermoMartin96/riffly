# Manual testing guide (macOS, Chrome)

For the tech lead's hands-on testing and for building the real-guitar validation set
(`docs/research/real-recording-validation-protocol.md`).

## 1. Start JamRecall
```sh
cd <repo>                       # this worktree / your clone, on feature/m1-audio-riff-slice
git pull
./scripts/dev.sh
```
- First run installs the backend venv (~2 min) and frontend packages. Later starts take about 6 s;
  most of that is loading the Basic Pitch model.
- It picks Node 25.4.0 through nvm automatically (your nvm default, 18.7, is too old for Vite 8).
- Open **http://127.0.0.1:5173** in Chrome once it prints "JamRecall is running". Use `127.0.0.1` or
  `localhost`; other hostnames are not a secure context and the microphone will be blocked.
- The API runs on port **8700**. Port 8000 is already used on this Mac by another FastAPI app, so if a
  port is busy the script stops and tells you which program holds it. Other ports:
  `JAMRECALL_API_PORT=8710 JAMRECALL_WEB_PORT=5180 ./scripts/dev.sh`.
- Ctrl-C stops both servers.

## 2. Where your data is saved
| What | Where |
|---|---|
| Original recordings (byte-for-byte) | `var/media/sessions/<session id>/original.webm` |
| Sessions, transcription runs, annotations, riffs | `var/jamrecall.sqlite3` |
| Exports you download | your browser's Downloads folder (`jamrecall-<id>.zip`) |
| Reference annotations and holdout provenance | in the database above. The validation gate reads them from there; `bench/real/references/*.json` (from `export-references`) are archival copies only |

`var/` is in `.gitignore`, so recordings are never committed. Reference JSON files (notes and metadata,
no audio) are meant to be committed. Use `JAMRECALL_DATA_DIR=/some/path ./scripts/dev.sh` to keep a
separate data set.

Deleting data:
- In the app: open a recording → **Delete recording…** → confirm. This permanently removes the
  audio, riffs, transcriptions and annotation.
- Command line: `backend/.venv/bin/python -m jamrecall.manage list | delete-session <id> --yes | wipe --yes`
  (`where` prints the paths).

## 3. Microphone setup and known macOS issues
- **macOS permission**: the first time, Chrome asks for the microphone. If you clicked "Don't allow"
  or recording shows "Microphone access was denied":
  - System Settings → Privacy & Security → Microphone → enable **Google Chrome**, then quit and
    reopen Chrome;
  - and in Chrome: click the icon left of the address bar → Microphone → Allow → reload.
- **Wrong input**: Chrome uses its own default device. Pick your interface or mic at
  `chrome://settings/content/microphone` and reload the page.
- **Mic Mode (Voice Isolation)**: while Chrome is using the mic, open Control Center → Mic Mode and
  choose **Standard**. Voice Isolation and Wide Spectrum alter the guitar tone and attacks. JamRecall
  already disables Chrome's echo cancellation, noise suppression and auto-gain.
- **Avoid Bluetooth headsets (AirPods etc.)**: when their mic is active they switch to a low-quality
  call codec (16–24 kHz).
- **Monitoring**: JamRecall does not play your input back while you record. For electric guitar
  through an interface, monitor through the interface or amp.
- **Levels**: aim for peaks well below clipping. The waveform should not hit the top of its lane.
- Known: Chrome reports a recording's length up to one Opus frame (≤ 60 ms) shorter than the server's
  measurement. The start of the recording is aligned exactly, so notes and riffs line up with playback.

## 4. Your first riff (walkthrough)
1. Click **● Record**, allow the microphone, play a short single-note riff (5–15 s), click **■ Stop**.
   The recording opens with its waveform and duration.
2. Click **▶ Play** to listen to the original. Click anywhere on the timeline to move the playhead;
   use **Zoom** to spread the timeline.
3. Click **Transcribe**. Within a second or two you get the ♪ row of detected pitches and the
   inferred tab. The engine is labelled *provisional* until the validation gate passes.
4. In **Reference annotation** click **Start from model output** (fine for this exploratory take).
   Then correct it:
   - **wrong pitch**: type a note name (`E4`, `F#3`, `Bb2`) or MIDI number in the Pitch box and press
     Enter, or use ♭/♯ to step a semitone;
   - **false positive**: ✕ on the row;
   - **missed note**: click the timeline where the note starts → **+ Add note at playhead**, then fix
     its end and pitch;
   - **timing**: type the time, use −/+ (10 ms steps), or play to the right spot and press ⌖ to
     copy the playhead;
   - **check a note**: ▶ on the row plays just that note.
   The green **ref** lane on the timeline shows your notes against the model's ♪ row. The model's
   transcription itself is never changed.
5. Leave **Split** on "— (exploratory)" for now, set Annotator, then **Save draft**.
6. **Export .zip** downloads the original audio, `reference.json`, every transcription run and the
   metadata, including what Chrome reported about the microphone (sample rate, processing flags,
   device label).

## 5. Exploratory round (2–3 recordings, before the real dataset)
Goal: confirm recording, playback, transcription and annotation work with *your* guitar, room and mic.
Nothing from this round counts toward validation: leave **Split** on "— (exploratory)" and never
finalize these takes as dev or holdout.
1. Record 2–3 short takes, for example a slow scale, a simple melody, and a faster lick.
2. For each: play it back (does it sound right and complete?), transcribe, correct the notes
   (starting from model output is fine here), **Save draft**, and export once.
3. Work through the checklist in §6.
4. Note anything wrong: missed starts or ends of a take, clipped audio, timing that looks offset
   against what you hear, UI problems.
5. Send me the observations, plus the exports if you're willing. I'll fix issues before the real
   dataset is recorded.
6. **Delete the exploratory sessions afterwards** (Delete recording…). Never reuse an exploratory take
   as a dev or holdout recording: record the dataset takes fresh.

## 6. Manual verification checklist (real Chrome, your Mac)
Tick each item during the exploratory round and tell me any that fail.
- [ ] Microphone prompt appears; after allowing it, **● Record** → **■ Stop** opens the recording with a
      sensible duration.
- [ ] Denying the microphone (or turning Chrome off in System Settings → Microphone) shows the
      "Microphone access was denied" message. Re-enable it afterwards.
- [ ] **▶ Play** sounds identical to what you played: no dropouts, no clipping, not pitch-shifted.
- [ ] Clicking the timeline moves the playhead, and audio starts from that spot.
- [ ] **Transcribe** finishes within a few seconds and shows the provisional-engine warning.
- [ ] The ♪ row and the tab line up with the notes you hear (play a note, watch the cursor cross it).
- [ ] Save a riff (≈1 s) and press **Play**: playback stops at its end. Press **Loop**: it repeats
      inside the riff until **Stop loop**.
- [ ] **Background-tab check (manual-only; CI cannot reproduce real timer throttling).** Save a short
      riff (≈1 s) in the middle of a take of at least 10 s. Press **Play**, then within half a
      second switch to another Chrome tab (Cmd-Option-→), wait 5 s, and come back.
      Expected: you heard it stop at the riff end (≤ ~0.3 s late), and the playhead sits at the riff's end,
      **not** at the end of the take. Repeat with **Loop**: while hidden it keeps looping inside the
      riff; the playhead never passes the riff end. Also try minimising the window instead of switching
      tabs. Tell me the result either way. Reference: Codex interim review, finding 5.
- [ ] A riff ending exactly at the recording's end loops instead of stopping.
- [ ] Annotation: edit a pitch, nudge a time, add a note at the playhead, delete a note, **Save draft**,
      reload the page: the edits are still there, and the model's ♪ row is unchanged.
- [ ] **Export .zip** contains `audio/original.webm`, `reference.json`, `transcriptions.json`,
      `metadata.json`. In `metadata.json`, `capture_info.track_settings` shows your mic's sample rate,
      with echoCancellation / noiseSuppression / autoGainControl `false`.
- [ ] Holdout guard: on a new take the badge says **Holdout-eligible**. Click **Transcribe** → a
      warning appears → **Cancel** → still eligible. Click **Transcribe** → **Transcribe anyway** →
      the badge says **Not holdout-eligible** and stays so after a reload. On another take: Start
      blank → Split holdout → add a note → **Finalize** → **Transcribe** (no warning) → still
      eligible.
- [ ] **Delete recording…** removes it from the list, and `backend/.venv/bin/python -m jamrecall.manage list`
      no longer shows it.

## 7. Collecting the validation dataset
Authoritative rules: `docs/research/real-recording-validation-protocol.md` (thresholds and minimums
must not change without a new decision request).

### 7.1 What to record (minimums)
| Condition | What to play | Dev takes | Holdout takes | Holdout notes (sum) | Gates M1? |
|---|---|---|---|---|---|
| A | Clean acoustic guitar, single-note melodies at moderate tempo: scales, simple tunes, some rests and repeated notes | ≥ 2 | ≥ 3 | ≥ 60 | yes |
| B | Fast riffs (16th notes at ≥ 120 bpm) and wide leaps (≥ an octave), acoustic or clean electric | ≥ 2 | ≥ 3 | ≥ 60 | yes |
| C | Clean electric guitar (amp or DI, clean tone), single-note lines | ≥ 2 | ≥ 3 | ≥ 60 | yes |
| D | Distorted / overdriven electric, single-note lines | ≥ 1 | ≥ 2 | – | no (exploratory) |

So at least **15 independent takes** for the gating conditions A–C (6 dev + 9 holdout), plus 3
optional D takes. Each take:
- is a separate JamRecall recording, 10–60 s long;
- is a new performance (never a re-upload, a copy, or a reused exploratory take). Duplicate audio or
  sessions are refused, even across dev and holdout;
- is monophonic (single notes, no chords).

To reach ≥ 60 holdout notes with 3 takes, play about 20 or more distinct notes per holdout take.
Recording one or two extra holdout takes per condition is a sensible buffer, in case one has to be
excluded. Vary the material between takes; don't play the same phrase in dev and holdout.

### 7.2 Use a dedicated, fresh data directory
Record the whole validation dataset in its own data directory, created new for this purpose. The
gate only accepts a database whose contamination tracking covered its entire life; a database that
existed before this version is refused. Stop the app, then start it with:
```sh
JAMRECALL_DATA_DIR=$PWD/var-validation ./scripts/dev.sh
```
- Check that it prints `Data directory: …/var-validation`, and that a new take shows
  **Holdout-eligible**. In an older data directory every take shows *Not holdout-eligible: data
  directory existed before full contamination tracking*.
- Keep exploratory takes in the normal `var/`.
- Use this command every time you record or annotate dataset takes.
- Never delete or wipe `var-validation/` until validation is done.

### 7.3 Plan the split before you play
Decide for each take whether it is **dev** or **holdout before recording it**. For example, write a
list such as "A-dev-1, A-dev-2, A-hold-1, …". Never choose the split after seeing how the engine did
on a take.

### 7.4 Dev take (model-assisted annotation allowed)
1. **● Record** the take → listen back with **▶ Play** (re-record if it's flawed).
2. **Transcribe**.
3. Reference annotation → **Start from model output** → correct every note by listening (two passes).
4. Split **dev**, Condition, Method `manual` (or `score`), Annotator, setup (guitar / amp / mic,
   distance) → **Save draft** → **Finalize**.

### 7.5 Holdout take (blank annotation, no exposure to model notes)
1. **● Record** the take → listen back with **▶ Play** (re-record if it's flawed).
2. **Do not click Transcribe.** The recording shows **Holdout-eligible** in green under its title.
   If you click Transcribe before finalizing, the app warns that this would permanently disqualify
   the take; choose **Cancel**. As long as the take has no transcription, the timeline shows no model
   notes and **Start from model output** is disabled.
3. Reference annotation → **Start blank** → set Split **holdout** right away.
4. Annotate by ear and waveform: zoom in, click the attack to place the playhead, **+ Add note at
   playhead**, type the pitch, set the end with ⌖ or the time box, check each note with ▶. Do a second
   full listening pass. Tag bends, slides etc. in Technique.
   Or use method `score`: play a written phrase to a click, then enter its pitches and correct every
   onset by hand.
5. Condition, Annotator, setup → **Save draft** → **Finalize**. The split is now locked for good.
6. Only **after** finalizing may you click **Transcribe** on that take, if you want to look.
   You don't need to: the gate runs both engines itself.

What makes a holdout reference invalid (the gate excludes it automatically, listing the reason):
- It was started from model output (seed recorded).
- Model output was requested before the reference was finalized: you chose **Transcribe anyway**.
  The badge turns to **Not holdout-eligible**, permanently.
- The reference was reopened after model output was requested (**Reopen anyway**).
- Its audio is identical to a recording that was disqualified before.
- Another recording in the data directory has the same audio (for example, an imported copy).
  This lasts only while the copy exists.
In each case, use the take as dev (or delete it) and record a replacement holdout take. Check the
badge before finalizing a holdout take: it must say **Holdout-eligible**.

### 7.6 Changing a finalized reference
- **Reopen for edits** keeps the split locked and increments the reference's revision. A finalized
  reference cannot change in any other way.
- Before any validation run: correcting a holdout reference is allowed (for example, a typo found on
  re-listening), **provided no model output was requested for that take**. If it was, **Reopen**
  warns that it would disqualify the take. Say why you're correcting it in the Notes field.
- After a validation run: the gate has produced model output for every finalized take, so
  **Reopen** warns, and continuing permanently disqualifies that take as holdout. If a holdout
  reference is genuinely wrong, tell me instead: the change needs a new decision request recorded
  with its reason and the before/after scores, because edits made after seeing results bias the
  evaluation.
- Do not wipe `var-validation/` while it holds the validation dataset: that erases provenance.

### 7.7 When the takes are done
Tell me the dataset is ready and I'll run it, or run it yourself:
```sh
cd bench
../backend/.venv/bin/python -m jamrecall_bench.real validate --data-dir ../var-validation
```
- `validate` reads every **finalized** reference and its provenance directly from the app database.
  It checks each original recording against the hashes stored at upload, decodes it with the app's
  own decoder, and runs Basic Pitch (with the app's parameters) and pYIN on it.
- It prints **PASS**, **FAIL** or **INCOMPLETE**, lists every excluded holdout take with its reason,
  shows the scores per condition, and writes `bench/results/real-validation.json`.
- Exported or hand-edited files are not inputs, so they can't change the result.
- Optional archival copy of the references (not used by the gate):
  `JAMRECALL_DATA_DIR=$PWD/var-validation backend/.venv/bin/python -m jamrecall.manage export-references --out bench/real/references`.
- Pass/fail criteria: protocol, "Pass criteria".
