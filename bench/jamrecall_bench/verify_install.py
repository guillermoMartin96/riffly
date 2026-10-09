"""Run inside a fresh Basic Pitch venv (see clean_install_test.sh). Exits non-zero on failure."""

from __future__ import annotations

import sys

import numpy as np

from jamrecall_bench.common import CACHE, CORPUS, RESULTS, load_manifest, read_json
from jamrecall_bench.methods import bp_analyse, bp_notes


def main() -> int:
    params = read_json(RESULTS / "basic-pitch.json")["selected_params"]
    synth = [c for c in load_manifest("synthetic")["clips"]
             if c["id"] == "scale_up_t+2_110bpm_clean"][0]
    est = bp_notes(bp_analyse(CORPUS / synth["audio"]), params)
    ref_p = [n["midi"] for n in synth["notes"]]
    est_p = [n["midi"] for n in est]
    print(f"smoke: reference pitches {ref_p}")
    print(f"smoke: detected pitches  {est_p}")
    ok = est_p == ref_p

    clips = [c for c in load_manifest("guitarset")["clips"] if c["split"] == "holdout"][:20]
    mismatched = 0
    for c in clips:
        cached = np.load(CACHE / "features" / "basic-pitch" / "guitarset" / f"{c['id']}.npz")
        bench = bp_notes({k: cached[k] for k in cached.files}, params)
        fresh = bp_notes(bp_analyse(CORPUS / c["audio"]), params)
        same = len(bench) == len(fresh) and all(
            a["midi"] == b["midi"] and abs(a["start"] - b["start"]) < 1e-6
            and abs(a["end"] - b["end"]) < 1e-6 for a, b in zip(bench, fresh, strict=True))
        mismatched += not same
    print(f"reproducibility: {len(clips) - mismatched}/{len(clips)} holdout clips give identical "
          f"notes to the benchmark venv")
    ok = ok and mismatched == 0
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
