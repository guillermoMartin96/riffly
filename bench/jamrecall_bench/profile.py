"""Resource profile of one method in a fresh process, on whole GuitarSet holdout solo recordings
(20-60 s each, closer to a real practice take than the short segments).

Usage: <venv>/bin/python -m jamrecall_bench.profile <method>
  -> bench/results/profile-<method>.json

Measures: import + model load time, first-call latency (includes JIT/graph warm-up), warm
real-time factor (processing seconds / audio seconds), CPU-seconds per wall-second (thread use),
and peak resident memory of the process (ru_maxrss).
"""

from __future__ import annotations

import os
import platform
import resource
import sys
import time

import soundfile as sf

from jamrecall_bench.common import CACHE, RESULTS, read_json, write_json

FILES = [
    "03_BN1-129-Eb_solo", "03_Funk2-119-G_solo", "04_Jazz1-200-B_solo",
    "04_Rock2-142-D_solo", "05_SS1-100-C#_solo", "05_BN3-119-G_solo",
]


def main() -> None:
    method = sys.argv[1]
    t0 = time.perf_counter()
    from jamrecall_bench import methods

    analyse, to_notes, spec = methods.METHODS[method]
    # Profile with the parameters selected on GuitarSet dev by jamrecall_bench.run.
    params = read_json(RESULTS / f"{method}.json")["selected_params"] if spec else {}
    if method == "basic-pitch":
        methods.bp_model()
    if method == "pyin":
        import librosa  # noqa: F401
    load_s = time.perf_counter() - t0

    src = CACHE / "guitarset" / "audio_mono-mic"
    paths = [src / f"{f}_mic.wav" for f in FILES if (src / f"{f}_mic.wav").exists()]
    durations = [sf.info(p).duration for p in paths]

    t = time.perf_counter()
    to_notes(analyse(paths[0]), params)
    first_s = time.perf_counter() - t

    wall0, cpu0 = time.perf_counter(), time.process_time()
    for p in paths[1:]:
        to_notes(analyse(p), params)
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss / 1e6 if sys.platform == "darwin" else rss / 1e3

    out = {
        "method": method,
        "params": params,
        "files": [p.name for p in paths],
        "import_and_model_load_s": round(load_s, 2),
        "first_call": {"audio_s": round(durations[0], 1), "latency_s": round(first_s, 2)},
        "warm": {
            "audio_s": round(sum(durations[1:]), 1),
            "wall_s": round(wall, 2),
            "real_time_factor": round(wall / sum(durations[1:]), 4),
            "cpu_s_per_wall_s": round(cpu / wall, 2),
        },
        "peak_rss_mb": round(rss_mb, 1),
        "environment": {
            "python": platform.python_version(), "machine": platform.machine(),
            "cpu_count": os.cpu_count(), "platform": platform.platform(),
        },
    }
    write_json(RESULTS / f"profile-{method}.json", out)
    print(out)


if __name__ == "__main__":
    main()
