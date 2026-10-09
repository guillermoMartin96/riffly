"""Run one method over the corpora: analyse (cached), tune on dev, evaluate dev + holdout.

Usage (from bench/, inside the method's venv):
  .venv-pyin/bin/python -m jamrecall_bench.run pyin
  .venv-bp/bin/python   -m jamrecall_bench.run basic-pitch
  .venv-pyin/bin/python -m jamrecall_bench.run fixture

Parameters are selected by onset F1 on the GuitarSet *dev* split only, then reported unchanged on
both corpora and both splits. Writes bench/results/<method>.json.
"""

from __future__ import annotations

import platform
import sys
import time
from collections import defaultdict

import numpy as np

from jamrecall_bench.common import CACHE, CORPUS, RESULTS, load_manifest, write_json
from jamrecall_bench.methods import METHODS, grid
from jamrecall_bench.score import aggregate, clip_stats

CORPORA = ("guitarset", "synthetic")


def analyse_all(method: str) -> dict[str, dict]:
    analyse, _, _ = METHODS[method]
    feats, timing = {}, {}
    for corpus in CORPORA:
        for clip in load_manifest(corpus)["clips"]:
            cache = CACHE / "features" / method / corpus / f"{clip['id']}.npz"
            key = f"{corpus}/{clip['id']}"
            if cache.exists():
                data = np.load(cache, allow_pickle=False)
                feats[key] = {k: data[k] for k in data.files}
                continue
            t0 = time.perf_counter()
            a = analyse(CORPUS / clip["audio"])
            a["analysis_seconds"] = np.float64(time.perf_counter() - t0)
            cache.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(cache, **a)
            feats[key] = a
            timing[key] = float(a["analysis_seconds"])
            if len(timing) % 50 == 0:
                print(f"  analysed {len(timing)} clips", flush=True)
    return feats


def evaluate(method: str, feats: dict, params: dict, corpus: str, split: str):
    _, to_notes, _ = METHODS[method]
    stats, by_tag = [], defaultdict(list)
    conv_s = analysis_s = audio_s = 0.0
    for clip in load_manifest(corpus)["clips"]:
        if clip["split"] != split:
            continue
        a = feats[f"{corpus}/{clip['id']}"]
        t0 = time.perf_counter()
        est = to_notes(a, params)
        conv_s += time.perf_counter() - t0
        analysis_s += float(a.get("analysis_seconds", 0.0))
        audio_s += clip["duration"]
        s = clip_stats(clip["notes"], est)
        stats.append(s)
        for tag in ("phrase", "condition", "bpm", "style"):
            if tag in clip["tags"]:
                by_tag[f"{tag}={clip['tags'][tag]}"].append(s)
    result = aggregate(stats)
    result["audio_minutes"] = round(audio_s / 60, 2)
    result["real_time_factor"] = round((analysis_s + conv_s) / audio_s, 4) if audio_s else None
    result["by_tag"] = {k: aggregate(v)["onset"] | {"n_ref": aggregate(v)["n_ref"]}
                        for k, v in sorted(by_tag.items())}
    return result


def main() -> None:
    method = sys.argv[1]
    _, _, spec = METHODS[method]
    print(f"[{method}] analysing corpora", flush=True)
    feats = analyse_all(method)
    candidates = grid(spec) or [{}]
    print(f"[{method}] tuning {len(candidates)} parameter sets on guitarset/dev", flush=True)
    tuning = []
    for p in candidates:
        r = evaluate(method, feats, p, "guitarset", "dev")
        tuning.append({"params": p, "onset_f1": r["onset"]["f1"],
                       "onset_offset_f1": r["onset_offset"]["f1"]})
    best = max(tuning, key=lambda t: (t["onset_f1"], t["onset_offset_f1"]))["params"]
    print(f"[{method}] selected {best}", flush=True)
    results = {
        "method": method,
        "selected_params": best,
        "selection": "max onset F1 on guitarset/dev",
        "environment": {"python": platform.python_version(), "machine": platform.machine(),
                        "platform": platform.platform()},
        "tuning": sorted(tuning, key=lambda t: -t["onset_f1"])[:10],
        "results": {f"{c}/{s}": evaluate(method, feats, best, c, s)
                    for c in CORPORA for s in ("dev", "holdout")},
    }
    if method == "basic-pitch":
        poly = dict(best, mono=False)
        results["results_raw_polyphonic"] = {
            f"{c}/{s}": evaluate(method, feats, poly, c, s) for c in CORPORA
            for s in ("dev", "holdout")
        }
    write_json(RESULTS / f"{method}.json", results)
    for k, v in results["results"].items():
        print(f"  {k:20s} onset F1 {v['onset']['f1']:.3f}  "
              f"P {v['onset']['precision']:.3f} R {v['onset']['recall']:.3f}  "
              f"w/offset F1 {v['onset_offset']['f1']:.3f}  RTF {v['real_time_factor']}")


if __name__ == "__main__":
    main()
