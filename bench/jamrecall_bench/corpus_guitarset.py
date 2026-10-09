"""Monophonic segments from GuitarSet v1.1.0 solo excerpts (real acoustic guitar, mic audio).

Source: Xi, Bittner, Pauwels, Ye, Bello, "GuitarSet: A Dataset for Guitar Transcription",
ISMIR 2018.
Zenodo DOI 10.5281/zenodo.3371780, license CC BY 4.0. Six players recorded with a hexaphonic pickup;
note annotations were derived per string from the hexaphonic signal and manually corrected by the
authors. We use `audio_mono-mic` (reference microphone) and the `note_midi` annotations.

Solos are mostly single-line but contain double stops and ringing notes (16% of successive note
pairs overlap > 30 ms). We keep maximal runs of notes where each note starts no earlier than
30 ms before the previous one ends (small overlaps are trimmed at the next onset), require >= 4
notes, and crop the audio so that no annotated note outside the run sounds inside the crop
(leading/trailing notes are dropped when a neighbour still rings into them).
Split by player: dev = players 00-02, holdout = players 03-05.

Usage: python -m jamrecall_bench.corpus_guitarset  (expects bench/.cache/guitarset/ extracted)
"""

from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path

import soundfile as sf

from jamrecall_bench.common import CACHE, CORPUS, write_json

SRC = CACHE / "guitarset"
OVERLAP_TOL = 0.03
MIN_NOTES = 4
PAD = 0.15
EXPECTED_MD5 = {
    "annotation.zip": "b39b78e63d3446f2e54ddb7a54df9b10",
    "audio_mono-mic.zip": "275966d6610ac34999b58426beb119c3",
}


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_notes(jams_path: str) -> list[dict]:
    j = json.load(open(jams_path))
    notes = []
    for a in j["annotations"]:
        if a["namespace"] != "note_midi":
            continue
        string_idx = a["annotation_metadata"]["data_source"]  # 0 = low E
        for d in a["data"]:
            notes.append({
                "start": float(d["time"]), "end": float(d["time"] + d["duration"]),
                "midi_float": float(d["value"]), "midi": int(round(d["value"])),
                "string_low_e_0": int(string_idx),
            })
    notes.sort(key=lambda n: (n["start"], n["midi"]))
    return notes


def mono_runs(notes: list[dict]) -> list[list[dict]]:
    """Index runs of consecutive notes with no overlap beyond OVERLAP_TOL (trimmed copies)."""
    runs, cur = [], []
    for i, n in enumerate(notes):
        if cur and n["start"] < notes[cur[-1]]["end"] - OVERLAP_TOL:
            runs.append(cur)
            cur = []
        cur.append(i)
    runs.append(cur)
    return runs


def crop_run(notes: list[dict], idx: list[int], dur: float):
    """Shrink a run until a crop window exists that contains no other annotated sound.

    Leading notes are dropped while an earlier note still rings into the first kept note; trailing
    notes are dropped while a later note starts at/before the last kept note's onset.
    """
    idx = list(idx)
    while idx:
        first = notes[idx[0]]
        prev_end = max((n["end"] for n in notes[: idx[0]]), default=0.0)
        if prev_end <= first["start"]:
            break
        idx.pop(0)
    while idx:
        last = notes[idx[-1]]
        next_start = min((n["start"] for n in notes[idx[-1] + 1 :]), default=dur)
        if next_start > last["start"] + 0.05:
            break
        idx.pop()
    if len(idx) < MIN_NOTES:
        return None
    prev_end = max((n["end"] for n in notes[: idx[0]]), default=0.0)
    next_start = min((n["start"] for n in notes[idx[-1] + 1 :]), default=dur)
    lo = max(0.0, notes[idx[0]]["start"] - PAD, prev_end)
    hi = min(dur, notes[idx[-1]]["end"] + PAD, next_start)
    run = [dict(notes[i]) for i in idx]
    for x, y in zip(run, run[1:], strict=False):
        x["end"] = min(x["end"], y["start"])  # trim <= 30 ms overlaps -> strictly monophonic
    run[-1]["end"] = min(run[-1]["end"], hi)
    return lo, hi, run


def main() -> None:
    for name, digest in EXPECTED_MD5.items():
        got = md5(SRC / name)
        assert got == digest, f"{name}: md5 {got} != {digest}"
    clips = []
    skipped = 0
    for jams in sorted(glob.glob(str(SRC / "annotation" / "*_solo.jams"))):
        stem = Path(jams).stem
        player = stem[:2]
        split = "dev" if player in {"00", "01", "02"} else "holdout"
        notes = load_notes(jams)
        audio, sr = sf.read(SRC / "audio_mono-mic" / f"{stem}_mic.wav", dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        dur = len(audio) / sr
        for k, idx in enumerate(mono_runs(notes)):
            cropped = crop_run(notes, idx, dur)
            if cropped is None:
                skipped += 1
                continue
            lo, hi, run = cropped
            seg = audio[int(lo * sr) : int(hi * sr)]
            seg_dur = len(seg) / sr  # sample-rounded; clamp ends to it
            ref = [{"start": round(n["start"] - lo, 6),
                    "end": round(min(n["end"] - lo, seg_dur), 6), "midi": n["midi"]}
                   for n in run if n["end"] > n["start"]]
            cid = f"{stem}_seg{k:02d}"
            path = CORPUS / "guitarset" / split / f"{cid}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(path, seg, sr, subtype="PCM_16")
            clips.append({
                "id": cid, "split": split, "audio": str(path.relative_to(CORPUS)),
                "duration": round(len(seg) / sr, 6), "notes": ref,
                "tags": {"player": player, "style": stem.split("_")[1].split("-")[0][:-1],
                         "source": stem, "offset_in_source": round(lo, 6)},
            })
    write_json(CORPUS / "guitarset" / "manifest.json", {
        "corpus": "guitarset",
        "description": "GuitarSet v1.1.0 solo excerpts, mic audio, monophonic segments "
                       "(CC BY 4.0, doi:10.5281/zenodo.3371780).",
        "clips": clips,
    })
    for split in ("dev", "holdout"):
        cs = [c for c in clips if c["split"] == split]
        print(f"guitarset {split}: {len(cs)} segments, "
              f"{sum(c['duration'] for c in cs) / 60:.1f} min, "
              f"{sum(len(c['notes']) for c in cs)} notes")
    print(f"skipped {skipped} runs with < {MIN_NOTES} notes after excluding neighbouring sound")


if __name__ == "__main__":
    main()
