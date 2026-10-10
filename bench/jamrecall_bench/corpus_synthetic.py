"""Synthetic plucked-string corpus with exact labels (Karplus-Strong).

SYNTHETIC AUDIO: this is not a guitar recording. It exists because its labels are exact and it
covers each protocol category deterministically: single notes across the range, ascending and
descending scales, rests, repeated same-pitch notes, several tempi, and clean / noisy / reverberant
conditions. Dev and holdout use different random seeds and different phrase transpositions.

Usage: python -m jamrecall_bench.corpus_synthetic
"""

from __future__ import annotations

import numpy as np
import soundfile as sf

from jamrecall_bench.common import CORPUS, write_json

SR = 44100


def pluck(midi: int, seconds: float, rng: np.random.Generator, brightness: float) -> np.ndarray:
    freq = 440.0 * 2 ** ((midi - 69) / 12) * 2 ** (rng.normal(0, 4) / 1200)  # +-few cents
    n = int(seconds * SR)
    period = SR / freq
    p = int(period)
    frac = period - p
    buf = rng.uniform(-1, 1, p + 1)
    # pluck-position comb + lowpass for a guitar-like attack
    buf = np.convolve(buf, [brightness, 1 - brightness], mode="same")
    out = np.empty(n)
    decay = 0.996 if midi < 60 else 0.993
    for i in range(n):
        j = i % (p + 1)
        out[i] = buf[j]
        nxt = buf[(j + 1) % (p + 1)]
        buf[j] = decay * ((1 - frac) * buf[j] + frac * nxt) * 0.5 + decay * buf[j] * 0.5
    attack = np.minimum(1.0, np.arange(n) / (0.002 * SR))
    return out * attack


def render(notes: list[dict], total: float, rng: np.random.Generator) -> np.ndarray:
    y = np.zeros(int(total * SR) + SR)
    for nt in notes:
        dur = nt["end"] - nt["start"]
        tone = pluck(nt["midi"], dur + 0.03, rng, rng.uniform(0.3, 0.7))
        fade = int(0.03 * SR)  # damped at the labelled offset (30 ms release)
        tone[-fade:] *= np.linspace(1, 0, fade)
        a = int(nt["start"] * SR)
        y[a : a + tone.size] += tone * rng.uniform(0.5, 0.9)
    return y[: int(total * SR)]


def add_condition(y: np.ndarray, cond: str, rng: np.random.Generator) -> np.ndarray:
    if cond == "noise20db":
        noise = np.cumsum(rng.normal(0, 1, y.size))  # brown-ish room noise
        noise = noise - np.convolve(noise, np.ones(441) / 441, mode="same")
        noise *= np.sqrt(np.mean(y**2) / np.mean(noise**2)) / 10  # 20 dB SNR
        return y + noise
    if cond == "reverb":
        t = np.arange(int(0.5 * SR)) / SR
        rir = rng.normal(0, 1, t.size) * np.exp(-t * 6.9 / 0.45)  # RT60 ~0.45 s
        rir[0] = 1.0
        wet = np.convolve(y, rir)[: y.size]
        wet *= np.sqrt(np.mean(y**2) / max(1e-12, np.mean(wet**2)))
        return 0.6 * y + 0.4 * wet
    return y


def phrases(transpose: int) -> dict[str, list[tuple[int | None, float]]]:
    """Name -> list of (midi or None for rest, beats)."""
    major = [0, 2, 4, 5, 7, 9, 11, 12]
    pent = [0, 3, 5, 7, 10, 12]
    root = 52 + transpose  # E3-ish
    return {
        "single_low": [(40 + transpose % 5, 2.0)],
        "single_mid": [(57 + transpose, 2.0)],
        "single_high": [(76 + transpose, 2.0)],
        "scale_up": [(root + i, 0.5) for i in major],
        "scale_down": [(root + 12 + 12 - i - 12, 0.5) for i in major],
        "pentatonic_rests": [
            (root + pent[0], 0.5),
            (None, 0.5),
            (root + pent[1], 0.5),
            (root + pent[2], 0.5),
            (None, 1.0),
            (root + pent[3], 0.5),
            (root + pent[4], 0.5),
            (None, 0.5),
            (root + pent[5], 1.0),
        ],
        "repeated_notes": [(root + 7, 0.5)] * 4 + [(root + 5, 0.5)] * 3 + [(root + 7, 1.0)],
        "wide_leaps": [
            (45 + transpose, 0.5),
            (69 + transpose, 0.5),
            (50 + transpose, 0.5),
            (74 + transpose, 0.5),
            (43 + transpose, 1.0),
        ],
        "riff_16ths": [(root + x, 0.25) for x in (0, 3, 5, 3, 7, 5, 3, 0, 10, 7, 5, 3, 0, 0)],
    }


def build_split(split: str, seed: int, transposes: list[int]) -> list[dict]:
    rng = np.random.default_rng(seed)
    out_dir = CORPUS / "synthetic" / split
    clips = []
    for tr in transposes:
        for name, seq in phrases(tr).items():
            for bpm in (70, 110, 150):
                if name.startswith("single") and bpm != 110:
                    continue
                for cond in ("clean", "noise20db", "reverb"):
                    beat = 60.0 / bpm
                    t = 0.3
                    notes = []
                    for midi, beats in seq:
                        dur = beats * beat
                        if midi is not None:
                            notes.append(
                                {
                                    "start": round(t, 6),
                                    "end": round(t + dur * 0.92, 6),
                                    "midi": int(midi),
                                }
                            )
                        t += dur
                    total = t + 0.5
                    y = add_condition(render(notes, total, rng), cond, rng)
                    y = 0.7 * y / max(1e-9, np.max(np.abs(y)))
                    cid = f"{name}_t{tr:+d}_{bpm}bpm_{cond}"
                    path = out_dir / f"{cid}.wav"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    sf.write(path, y.astype(np.float32), SR, subtype="PCM_16")
                    clips.append(
                        {
                            "id": cid,
                            "split": split,
                            "audio": str(path.relative_to(CORPUS)),
                            "duration": round(total, 6),
                            "notes": notes,
                            "tags": {
                                "phrase": name,
                                "bpm": bpm,
                                "condition": cond,
                                "transpose": tr,
                            },
                        }
                    )
    return clips


def main() -> None:
    clips = build_split("dev", seed=1, transposes=[0, 5]) + build_split(
        "holdout", seed=2, transposes=[2, 7]
    )
    write_json(
        CORPUS / "synthetic" / "manifest.json",
        {
            "corpus": "synthetic",
            "description": "Karplus-Strong plucked-string synthesis with exact labels. "
            "NOT real guitar.",
            "sample_rate": SR,
            "clips": clips,
        },
    )
    print(
        f"synthetic: {len(clips)} clips, "
        f"{sum(c['duration'] for c in clips) / 60:.1f} min, "
        f"{sum(len(c['notes']) for c in clips)} notes"
    )


if __name__ == "__main__":
    main()
