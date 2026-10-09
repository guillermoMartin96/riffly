"""Real-recording validation (docs/research/real-recording-validation-protocol.md).

From bench/:
  ../backend/.venv/bin/python -m jamrecall_bench.real prepare --data-dir ../var
  .venv-bp/bin/python   -m jamrecall_bench.real score basic-pitch [--tune-on-dev]
  .venv-pyin/bin/python -m jamrecall_bench.real score pyin [--tune-on-dev]
  .venv-pyin/bin/python -m jamrecall_bench.real gate

--tag NAME (default "real") selects bench/real/<refs> + corpus/results names; any tag other than
"real" (e.g. a tooling dry run) writes its outputs under .cache/ so they cannot be mistaken for
validation evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

from jamrecall_bench.common import BENCH, CACHE, CORPUS, RESULTS, read_json, write_json
from jamrecall_bench.score import aggregate, clip_stats

GATING = ("A", "B", "C")
# condition -> (min dev recordings, min holdout recordings, min holdout notes)
MINIMUMS = {"A": (2, 3, 60), "B": (2, 3, 60), "C": (2, 3, 60), "D": (1, 2, 0)}
GATE_F1 = 0.80
POOR_F1 = 0.70  # per gating condition; provisionally approved 2026-10-09
POOR_PITCH = 0.90  # exact-pitch rate per gating condition; provisionally approved 2026-10-09


def is_engine_seed(seed: str | None) -> bool:
    return bool(seed) and seed.startswith("transcription:")


def results_dir(tag: str) -> Path:
    return RESULTS if tag == "real" else CACHE / "dryrun" / tag


def validate_reference(ref: dict, name: str) -> list[str]:
    errs = []
    for k in ("session_id", "audio_sha256", "split", "condition", "method", "notes"):
        if k not in ref:
            errs.append(f"{name}: missing '{k}'")
    if ref.get("split") not in ("dev", "holdout"):
        errs.append(f"{name}: split must be dev or holdout")
    if ref.get("condition") not in MINIMUMS:
        errs.append(f"{name}: condition must be one of {sorted(MINIMUMS)}")
    if ref.get("method") not in ("manual", "score"):
        errs.append(f"{name}: method must be manual or score")
    if ref.get("status", "final") != "final":
        errs.append(f"{name}: annotation is not finalized (status {ref.get('status')})")
    notes = ref.get("notes") or []
    if not notes:
        errs.append(f"{name}: no reference notes")
    for i, n in enumerate(notes):
        if not (0 <= n["start"] < n["end"]) or not (0 <= int(n["midi"]) <= 127):
            errs.append(f"{name}: invalid note #{i} {n}")
    return errs


def prepare(args) -> int:
    import soundfile as sf
    from jamrecall.audio import decode_mono  # the app's own decoder (backend venv)

    data_dir = Path(args.data_dir).resolve()
    refs_dir = BENCH / args.tag / "references" if args.refs is None else Path(args.refs)
    refs = sorted(refs_dir.glob("*.json"))
    if not refs:
        print(f"no reference files in {refs_dir}")
        return 2
    conn = sqlite3.connect(data_dir / "jamrecall.sqlite3")
    clips, errors = [], []
    for path in refs:
        ref = json.loads(path.read_text())
        name = path.stem
        errs = validate_reference(ref, name)
        row = conn.execute(
            "SELECT audio_path, audio_sha256, duration_seconds FROM sessions WHERE id = ?",
            (ref.get("session_id"),),
        ).fetchone()
        if row is None:
            errs.append(f"{name}: session {ref.get('session_id')} not in {data_dir}")
        if errs:
            errors += errs
            continue
        audio_path = data_dir / row[0]
        digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()
        if not (digest == row[1] == ref["audio_sha256"]):
            errors.append(f"{name}: sha256 mismatch (file {digest[:12]}, db {row[1][:12]}, "
                          f"reference {ref['audio_sha256'][:12]})")
            continue
        buf = decode_mono(audio_path, 22050)
        out = CORPUS / args.tag / ref["split"] / f"{name}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(out, buf.samples, buf.sample_rate, subtype="FLOAT")
        clips.append({
            "id": name, "split": ref["split"], "audio": str(out.relative_to(CORPUS)),
            "duration": round(buf.duration_seconds, 6),
            "notes": [{"start": float(n["start"]), "end": float(n["end"]), "midi": int(n["midi"]),
                       "technique": n.get("technique")} for n in ref["notes"]],
            "tags": {"condition": ref["condition"], "method": ref["method"],
                     "seed": ref.get("seed", "blank"), "revision": ref.get("revision"),
                     "session_id": ref["session_id"], "audio_sha256": digest},
        })
    for e in errors:
        print("ERROR", e)
    write_json(CORPUS / args.tag / "manifest.json", {"corpus": args.tag, "clips": clips})
    for (cond, split), n in sorted(_counts(clips).items()):
        print(f"condition {cond} {split}: {n['recordings']} recordings, {n['notes']} notes")
    return 1 if errors else 0


def _counts(clips: list[dict]) -> dict:
    """Recordings/notes that count toward the minimums (engine-seeded holdout refs excluded)."""
    c: dict = defaultdict(lambda: {"recordings": 0, "notes": 0})
    for clip in clips:
        if clip["split"] == "holdout" and is_engine_seed(clip["tags"].get("seed")):
            continue
        k = (clip["tags"]["condition"], clip["split"])
        c[k]["recordings"] += 1
        c[k]["notes"] += len(clip["notes"])
    return c


def score(args) -> int:
    from jamrecall_bench.methods import METHODS, grid

    analyse, to_notes, spec = METHODS[args.method]
    params = read_json(RESULTS / f"{args.method}.json")["selected_params"] if spec else {}
    clips = read_json(CORPUS / args.tag / "manifest.json")["clips"]
    feats, timing = {}, {}
    for c in clips:
        t0 = time.perf_counter()
        feats[c["id"]] = analyse(CORPUS / c["audio"])
        timing[c["id"]] = time.perf_counter() - t0
    tuned = None
    if args.tune_on_dev and spec:
        dev = [c for c in clips if c["split"] == "dev"]
        best = max(grid(spec), key=lambda p: aggregate(
            [clip_stats(c["notes"], to_notes(feats[c["id"]], p)) for c in dev])["onset"]["f1"])
        tuned, params = best, best

    per_rec, groups, excluded = {}, defaultdict(list), []
    for c in clips:
        t0 = time.perf_counter()
        est = to_notes(feats[c["id"]], params)
        proc = timing[c["id"]] + time.perf_counter() - t0
        s = clip_stats(c["notes"], est)
        plain = [n for n in c["notes"] if not n.get("technique")]
        s_plain = clip_stats(plain, est) if plain else None
        cond, split = c["tags"]["condition"], c["split"]
        per_rec[c["id"]] = aggregate([s]) | {
            "split": split, "condition": cond, "duration_s": c["duration"],
            "processing_s": round(proc, 3), "real_time_factor": round(proc / c["duration"], 4),
        }
        if split == "holdout" and is_engine_seed(c["tags"].get("seed")):
            # Protocol: a holdout reference seeded from engine output is not independent evidence.
            per_rec[c["id"]]["excluded_from_holdout"] = "reference seeded from engine output"
            excluded.append(c["id"])
            continue
        groups[(split, cond)].append((s, s_plain))
        if cond in GATING:
            groups[(split, "A+B+C")].append((s, s_plain))
    summary = {
        f"{split}/{cond}": aggregate([s for s, _ in v]) | {
            "excluding_technique_notes": aggregate([p for _, p in v if p is not None])["onset"]}
        for (split, cond), v in sorted(groups.items())
    }
    out = {"method": args.method, "params": params, "tuned_on_real_dev": tuned,
           "excluded_holdout_engine_seeded": excluded,
           "per_recording": per_rec, "summary": summary}
    write_json(results_dir(args.tag) / f"real-{args.method}.json", out)
    for k, v in summary.items():
        exact = v["pitch_on_onset_matched"]["exact"]
        print(f"  {k:18s} onset F1 {v['onset']['f1']:.3f}  pitch exact {exact:.3f}  "
              f"+offset F1 {v['onset_offset']['f1']:.3f}")
    return 0


def gate(args) -> int:
    d = results_dir(args.tag)
    bp, py = read_json(d / "real-basic-pitch.json"), read_json(d / "real-pyin.json")
    clips = read_json(CORPUS / args.tag / "manifest.json")["clips"]
    counts = _counts(clips)
    missing = []
    for cond, (n_dev, n_hold, n_notes) in MINIMUMS.items():
        dev, hold = counts.get((cond, "dev")), counts.get((cond, "holdout"))
        dev_n = (dev or {}).get("recordings", 0)
        hold_n, hold_notes = (hold or {}).get("recordings", 0), (hold or {}).get("notes", 0)
        if dev_n < n_dev or hold_n < n_hold or hold_notes < n_notes:
            missing.append(cond)
    key = "holdout/A+B+C"
    checks, poor = {}, []
    if key in bp["summary"] and key in py["summary"]:
        f_bp, f_py = bp["summary"][key]["onset"]["f1"], py["summary"][key]["onset"]["f1"]
        checks = {f"basic_pitch_onset_f1 >= {GATE_F1}": [f_bp, f_bp >= GATE_F1],
                  "basic_pitch_onset_f1 >= pyin_onset_f1": [[f_bp, f_py], f_bp >= f_py]}
    for cond in GATING:
        s = bp["summary"].get(f"holdout/{cond}")
        if s and (s["onset"]["f1"] < POOR_F1 or s["pitch_on_onset_matched"]["exact"] < POOR_PITCH):
            poor.append(cond)
    gating_missing = [c for c in missing if c in GATING]
    if gating_missing or not checks:
        verdict = "INCOMPLETE"
    elif all(ok for _, ok in checks.values()) and not poor:
        verdict = "PASS"
    else:
        verdict = "FAIL"
    result = {"verdict": verdict, "checks": checks, "poor_conditions": poor,
              "excluded_holdout_engine_seeded": bp.get("excluded_holdout_engine_seeded", []),
              "conditions_below_minimum": missing,
              "exploratory_D": bp["summary"].get("holdout/D", {}).get("onset"),
              "thresholds": {"gate_f1": GATE_F1, "condition_min_onset_f1": POOR_F1,
                             "condition_min_pitch_exact": POOR_PITCH}}
    write_json(d / "real-gate.json", result)
    print(json.dumps(result, indent=1))
    return {"PASS": 0, "FAIL": 1, "INCOMPLETE": 2}[verdict]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="real")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--data-dir", required=True)
    p.add_argument("--refs", default=None)
    s = sub.add_parser("score")
    s.add_argument("method", choices=["basic-pitch", "pyin"])
    s.add_argument("--tune-on-dev", action="store_true")
    sub.add_parser("gate")
    args = ap.parse_args()
    sys.exit({"prepare": prepare, "score": score, "gate": gate}[args.cmd](args))


if __name__ == "__main__":
    main()
