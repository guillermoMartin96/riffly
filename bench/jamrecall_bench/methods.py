"""Candidate transcription methods, split into an expensive analysis step (cached per clip) and a
cheap, parameterised note-extraction step (tuned on the dev split only).

- pyin:        librosa.pyin f0 + voicing, notes = runs of stable rounded pitch, split at detected
               onsets (handles repeated same-pitch notes), optional onset snapping.
- basic-pitch: Spotify Basic Pitch 0.4.0 ICASSP-2022 model via ONNX Runtime; notes from its
               note/onset posteriorgrams. "mono" variant enforces one note at a time.
- fixture:     the backend's TEST-ONLY fixture pattern, ignoring audio. A floor, not a method.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np

SR = 22050
HOP = 256
FMIN, FMAX = 75.0, 1400.0  # E2 = 82.4 Hz; 20th fret on high E = C6 = 1046.5 Hz


# --- pYIN -----------------------------------------------------------------------------------

def pyin_analyse(path: Path) -> dict[str, np.ndarray]:
    import librosa

    y, _ = librosa.load(path, sr=SR, mono=True)
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y, fmin=FMIN, fmax=FMAX, sr=SR, frame_length=2048, hop_length=HOP
    )
    onset_env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    return {
        "f0": f0.astype(np.float32), "voiced_flag": voiced_flag,
        "voiced_prob": voiced_prob.astype(np.float32), "onset_env": onset_env.astype(np.float32),
        "duration": np.float32(len(y) / SR),
    }


PYIN_GRID = {
    "voicing": ["flag", 0.3, 0.6],
    "median_frames": [1, 5],
    "onset_delta": [None, 0.1, 0.3],
    "min_note_s": [0.05, 0.1],
    "snap_onsets": [False, True],
}


def pyin_notes(a: dict[str, np.ndarray], p: dict) -> list[dict]:
    import librosa
    import scipy.signal

    f0 = a["f0"]
    voiced = a["voiced_flag"] if p["voicing"] == "flag" else a["voiced_prob"] >= p["voicing"]
    midi = np.full(f0.shape, -1, dtype=int)
    ok = voiced & np.isfinite(f0)
    midi[ok] = np.round(librosa.hz_to_midi(f0[ok])).astype(int)
    if p["median_frames"] > 1:
        midi = scipy.signal.medfilt(midi, p["median_frames"]).astype(int)
    onsets = np.array([], dtype=int)
    if p["onset_delta"] is not None or p["snap_onsets"]:
        onsets = librosa.onset.onset_detect(
            onset_envelope=a["onset_env"], sr=SR, hop_length=HOP,
            delta=p["onset_delta"] or 0.1, units="frames",
        )
    split_at = set(onsets.tolist()) if p["onset_delta"] is not None else set()
    notes: list[tuple[int, int, int]] = []
    start = None
    for i in range(len(midi) + 1):
        cur = midi[i] if i < len(midi) else -1
        boundary = start is not None and (cur != midi[start] or i in split_at)
        if boundary:
            notes.append((start, i, int(midi[start])))
            start = None
        if start is None and cur >= 0:
            start = i
    t = lambda f: f * HOP / SR  # noqa: E731
    out = []
    for s, e, m in notes:
        st, en = t(s), t(e)
        if p["snap_onsets"] and onsets.size:
            prior = onsets[(onsets <= s) & (onsets >= s - int(0.08 * SR / HOP))]
            if prior.size:
                st = t(int(prior.max()))
        if en - st >= p["min_note_s"]:
            out.append({"start": st, "end": en, "midi": m})
    return out


# --- Basic Pitch ----------------------------------------------------------------------------

_BP_MODEL = None


def bp_model():
    global _BP_MODEL
    if _BP_MODEL is None:
        from basic_pitch import ICASSP_2022_MODEL_PATH
        from basic_pitch.inference import Model

        _BP_MODEL = Model(Path(ICASSP_2022_MODEL_PATH).parent / "nmp.onnx")
    return _BP_MODEL


def bp_analyse(path: Path) -> dict[str, np.ndarray]:
    import soundfile as sf
    from basic_pitch.inference import run_inference

    out = run_inference(path, bp_model())
    info = sf.info(path)
    return {k: np.asarray(v, dtype=np.float32) for k, v in out.items()} | {
        "duration": np.float32(info.frames / info.samplerate)
    }


BP_GRID = {
    "onset_thresh": [0.3, 0.5, 0.7],
    "frame_thresh": [0.2, 0.3, 0.4],
    "min_note_ms": [58.0, 127.7],
    "mono": [False, True],
}


def bp_notes(a: dict[str, np.ndarray], p: dict) -> list[dict]:
    from basic_pitch.constants import AUDIO_SAMPLE_RATE, FFT_HOP
    from basic_pitch.note_creation import model_output_to_notes

    output = {k: a[k] for k in ("note", "onset", "contour")}
    _, events = model_output_to_notes(
        output, onset_thresh=p["onset_thresh"], frame_thresh=p["frame_thresh"],
        min_note_len=int(np.round(p["min_note_ms"] / 1000 * (AUDIO_SAMPLE_RATE / FFT_HOP))),
        min_freq=FMIN, max_freq=FMAX, include_pitch_bends=False, melodia_trick=True,
    )
    notes = sorted(
        ({"start": float(s), "end": float(e), "midi": int(m), "amp": float(amp)}
         for s, e, m, amp, _ in events),
        key=lambda n: (n["start"], -n["amp"]),
    )
    if p["mono"]:
        notes = monophonic(notes)
    return [{"start": n["start"], "end": n["end"], "midi": n["midi"]} for n in notes]


def monophonic(notes: list[dict]) -> list[dict]:
    """Keep one note at a time: among notes starting within 50 ms keep the loudest; a new onset
    truncates the sounding note."""
    out: list[dict] = []
    for n in notes:
        if out and n["start"] - out[-1]["start"] < 0.05:
            if n["amp"] > out[-1]["amp"]:
                out[-1] = dict(n)
            continue
        if out and out[-1]["end"] > n["start"]:
            out[-1]["end"] = n["start"]
        out.append(dict(n))
    return [n for n in out if n["end"] > n["start"]]


# --- fixture floor ----------------------------------------------------------------------------

def fixture_analyse(path: Path) -> dict[str, np.ndarray]:
    import soundfile as sf

    info = sf.info(path)
    return {"duration": np.float32(info.frames / info.samplerate)}


def fixture_notes(a: dict[str, np.ndarray], p: dict) -> list[dict]:
    pitches = [48, 49, 50, 51, 52, 53, 54, 55]  # same as backend FixtureAdapter
    out, t, i = [], 0.25, 0
    while t + 0.4 <= float(a["duration"]):
        out.append({"start": t, "end": t + 0.4, "midi": pitches[i % len(pitches)]})
        t += 0.5
        i += 1
    return out


METHODS = {
    "pyin": (pyin_analyse, pyin_notes, PYIN_GRID),
    "basic-pitch": (bp_analyse, bp_notes, BP_GRID),
    "fixture": (fixture_analyse, fixture_notes, {}),
}


def grid(spec: dict) -> list[dict]:
    keys = list(spec)
    return [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*spec.values())]
