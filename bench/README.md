# Transcription benchmark

Reproducible comparison of monophonic guitar transcription candidates for JamRecall (gate C of M1).
Protocol: `docs/research/transcription-evaluation.md`. Write-up: `docs/research/transcription-benchmark.md`.

Nothing here is a production dependency. Each candidate gets its own venv so its install footprint is
measured in isolation.

## Reproduce (macOS x86_64 / Linux, Python 3.12)

```sh
cd bench
sh install-pyin.sh          # .venv-pyin: librosa pYIN candidate + corpus tools + scoring
sh install-basicpitch.sh    # .venv-bp: Basic Pitch 0.4.0 (ONNX) — uses a --no-deps workaround

# GuitarSet v1.1.0 (CC BY 4.0): annotation.zip (39 MB) + audio_mono-mic.zip (657 MB)
mkdir -p .cache/guitarset && cd .cache/guitarset
curl -L -o annotation.zip https://zenodo.org/api/records/3371780/files/annotation.zip/content
curl -L -o audio_mono-mic.zip https://zenodo.org/api/records/3371780/files/audio_mono-mic.zip/content
unzip -q annotation.zip -d annotation && unzip -q audio_mono-mic.zip -d audio_mono-mic
cd ../..

.venv-pyin/bin/python -m jamrecall_bench.corpus_synthetic   # 252 synthetic clips (exact labels)
.venv-pyin/bin/python -m jamrecall_bench.corpus_guitarset   # verifies md5, cuts monophonic segments

.venv-pyin/bin/python -m jamrecall_bench.run fixture        # floor: test-only fixture
.venv-pyin/bin/python -m jamrecall_bench.run pyin
.venv-bp/bin/python   -m jamrecall_bench.run basic-pitch
.venv-pyin/bin/python -m jamrecall_bench.profile pyin
.venv-bp/bin/python   -m jamrecall_bench.profile basic-pitch
.venv-pyin/bin/python -m jamrecall_bench.report             # -> results/summary.md
```

Run the methods one at a time: per-clip timings are wall-clock and would be distorted by
concurrent runs. Analysis outputs are cached in `.cache/features/`; delete it to re-measure timing.

## Layout

| Path | Purpose |
|---|---|
| `jamrecall_bench/corpus_synthetic.py` | Karplus-Strong corpus: single notes, scales, rests, repeated notes, 70/110/150 bpm, clean/noise/reverb. **Synthetic, not guitar.** |
| `jamrecall_bench/corpus_guitarset.py` | Monophonic segments of GuitarSet solos (real acoustic guitar, mic), split by player |
| `jamrecall_bench/methods.py` | Candidates (analysis step + parameterised note extraction) and the fixture floor |
| `jamrecall_bench/score.py` | mir_eval note matching, shared tolerances, micro-averaged metrics |
| `jamrecall_bench/run.py` | Analyse → tune on GuitarSet dev → evaluate dev + holdout |
| `jamrecall_bench/profile.py` | Load time, latency, real-time factor, CPU use, peak RSS in a fresh process |
| `results/` | Committed result JSON and the generated `summary.md` |
