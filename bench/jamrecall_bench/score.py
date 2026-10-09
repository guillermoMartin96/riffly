"""Note-level scoring with mir_eval, identical for every method.

Tolerances (MIREX convention): onset +-50 ms, pitch +-50 cents; offset-aware matching additionally
requires the offset within max(50 ms, 20% of the reference note duration). Aggregates are
micro-averaged over all notes of a split.
"""

from __future__ import annotations

from collections import Counter

import mir_eval
import numpy as np

ONSET_TOL = 0.05
PITCH_TOL_CENTS = 50.0
OFFSET_RATIO = 0.2
OFFSET_MIN = 0.05


def _arrays(notes: list[dict]):
    if not notes:
        return np.zeros((0, 2)), np.zeros(0)
    iv = np.array([[n["start"], n["end"]] for n in notes], dtype=float)
    hz = mir_eval.util.midi_to_hz(np.array([n["midi"] for n in notes], dtype=float))
    return iv, hz


def clip_stats(ref: list[dict], est: list[dict]) -> dict:
    est = [n for n in est if n["end"] > n["start"]]
    r_iv, r_hz = _arrays(ref)
    e_iv, e_hz = _arrays(est)
    s = Counter(n_ref=len(ref), n_est=len(est))
    if not ref or not est:
        return dict(s) | {"onset_err": [], "offset_err": [], "pitch_diff": []}
    on = mir_eval.transcription.match_notes(
        r_iv, r_hz, e_iv, e_hz, onset_tolerance=ONSET_TOL, pitch_tolerance=PITCH_TOL_CENTS,
        offset_ratio=None,
    )
    off = mir_eval.transcription.match_notes(
        r_iv, r_hz, e_iv, e_hz, onset_tolerance=ONSET_TOL, pitch_tolerance=PITCH_TOL_CENTS,
        offset_ratio=OFFSET_RATIO, offset_min_tolerance=OFFSET_MIN,
    )
    onset_only = mir_eval.transcription.match_note_onsets(r_iv, e_iv, onset_tolerance=ONSET_TOL)
    s["tp_onset"] = len(on)
    s["tp_offset"] = len(off)
    s["onset_matched_any_pitch"] = len(onset_only)
    return dict(s) | {
        "onset_err": [float(e_iv[j, 0] - r_iv[i, 0]) for i, j in on],
        "offset_err": [float(e_iv[j, 1] - r_iv[i, 1]) for i, j in on],
        "pitch_diff": [int(est[j]["midi"] - ref[i]["midi"]) for i, j in onset_only],
    }


def aggregate(stats: list[dict]) -> dict:
    tot = Counter()
    onset_err, offset_err, pdiff = [], [], []
    for s in stats:
        for k in ("n_ref", "n_est", "tp_onset", "tp_offset", "onset_matched_any_pitch"):
            tot[k] += s.get(k, 0)
        onset_err += s["onset_err"]
        offset_err += s["offset_err"]
        pdiff += s["pitch_diff"]

    def prf(tp: int) -> dict:
        p = tp / tot["n_est"] if tot["n_est"] else 0.0
        r = tp / tot["n_ref"] if tot["n_ref"] else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}

    pd = np.array(pdiff)
    n_pd = max(1, pd.size)
    return {
        "clips": len(stats),
        "n_ref": tot["n_ref"],
        "n_est": tot["n_est"],
        "onset": prf(tot["tp_onset"]),
        "onset_offset": prf(tot["tp_offset"]),
        "onset_error_ms": {
            "mean_signed": round(1000 * float(np.mean(onset_err)), 1) if onset_err else None,
            "median_abs": round(1000 * float(np.median(np.abs(onset_err))), 1)
            if onset_err else None,
        },
        "offset_error_ms_median_abs": round(1000 * float(np.median(np.abs(offset_err))), 1)
        if offset_err else None,
        "pitch_on_onset_matched": {
            "n": int(pd.size),
            "exact": round(float(np.sum(pd == 0)) / n_pd, 4),
            "octave": round(float(np.sum((pd != 0) & (pd % 12 == 0))) / n_pd, 4),
            "semitone": round(float(np.sum(np.abs(pd) == 1)) / n_pd, 4),
            "other": round(float(np.sum((pd % 12 != 0) & (np.abs(pd) != 1))) / n_pd, 4),
        },
    }
