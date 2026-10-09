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
| Reference files for the validation gate | `bench/real/references/*.json` (created by `export-references`, below) |

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
Nothing from this round counts toward validation.
1. Record 2–3 short takes, for example a slow scale, a simple melody, and a faster lick.
2. For each: play it back (does it sound right and complete?), transcribe, correct the notes, save
   (split left exploratory), export once.
3. Note anything wrong: missed starts or ends of a take, clipped audio, timing that looks offset
   against what you hear, UI problems.
4. Send me the observations, plus the exports if you're willing. I'll fix issues before the real
   dataset is recorded.
5. Delete the exploratory sessions afterwards if you like (Delete recording…).

## 6. The validation dataset (after the exploratory round)
Follow `docs/research/real-recording-validation-protocol.md`. In short:
- **Conditions**:
  - A: clean acoustic melodies;
  - B: fast riffs (16ths at ≥ 120 bpm) and wide leaps (≥ an octave);
  - C: clean electric;
  - D: distorted electric (optional, exploratory).
- **Minimums**: A–C need at least 2 dev and 3 holdout recordings each, with at least 60 holdout notes
  per condition. D needs 1 dev and 2 holdout.
- **Decide dev or holdout before you annotate a take**, and set it in **Split**. After **Finalize**
  the split is locked for good.
- **Holdout references must start blank** (**Start blank**), annotated by ear and waveform (method
  "manual"), or from a known phrase you played to a click (method "score", with onsets corrected by
  hand). If a holdout reference is started from model output, the app warns you and the gate excludes
  it, because it would not be independent evidence (DR-0004 asks you to confirm this rule).
- **Dev** references may start from model output. Dev is the only place where anything may be tuned.
- Fill in Condition, Annotator and setup (guitar / amp / mic, distance), then **Finalize**.
- When the set is complete:
  ```sh
  backend/.venv/bin/python -m jamrecall.manage export-references --out bench/real/references
  cd bench
  ../backend/.venv/bin/python -m jamrecall_bench.real prepare --data-dir ../var
  .venv-bp/bin/python   -m jamrecall_bench.real score basic-pitch
  .venv-pyin/bin/python -m jamrecall_bench.real score pyin
  .venv-pyin/bin/python -m jamrecall_bench.real gate
  ```
  `bench/.venv-bp` and `bench/.venv-pyin` come from `sh bench/install-basicpitch.sh` and
  `sh bench/install-pyin.sh`. Or just tell me the recordings are ready and I'll run these steps and
  report the results without changing any thresholds.
