"""Real-recording validation (docs/research/real-recording-validation-protocol.md).

From bench/:
  ../backend/.venv/bin/python -m jamrecall_bench.real prepare --data-dir ../var
  .venv-bp/bin/python   -m jamrecall_bench.real score basic-pitch [--tune-on-dev]
  .venv-pyin/bin/python -m jamrecall_bench.real score pyin [--tune-on-dev]
  .venv-pyin/bin/python -m jamrecall_bench.real gate

Integrity rules (Codex interim review, 2026-10-09):
- references must be explicitly finalized and state their seed; duplicates of a session or of
  the same audio are refused; prepare writes no manifest unless every reference is valid;
- the manifest carries a content fingerprint; score results record it and the clip ids they
  scored; the gate refuses results that do not match the current manifest exactly;
- Basic Pitch is scored with the app's own parameters (backend/.../basic_pitch_params.json); a
  result tuned on dev, or scored with other parameters, cannot PASS.

--tag NAME (default "real") selects bench/<tag>/references and the corpus/results names; any tag
other than "real" (e.g. a tooling dry run) writes its outputs under .cache/ so they cannot be
mistaken for validation evidence.
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
from jamrecall_bench.score import ONSET_TOL, aggregate, clip_stats

GATING = ("A", "B", "C")
# condition -> (min dev recordings, min holdout recordings, min holdout notes)
MINIMUMS = {"A": (2, 3, 60), "B": (2, 3, 60), "C": (2, 3, 60), "D": (1, 2, 0)}
GATE_F1 = 0.80
POOR_F1 = 0.70  # per gating condition; provisionally approved 2026-10-09
POOR_PITCH = 0.90  # exact-pitch rate per gating condition; provisionally approved 2026-10-09
APP_PARAMS_FILE = (
    BENCH.parent / "backend" / "jamrecall" / "transcription" / "basic_pitch_params.json"
)
BENCH_BP_KEYS = ("onset_thresh", "frame_thresh", "min_note_ms", "mono")


def is_engine_seed(seed: str | None) -> bool:
    return bool(seed) and seed.startswith("transcription:")


def results_dir(tag: str) -> Path:
    return RESULTS if tag == "real" else CACHE / "dryrun" / tag


def app_bp_params() -> dict:
    data = json.loads(APP_PARAMS_FILE.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


# --- references ---------------------------------------------------------------------------------


def validate_reference(ref: dict, name: str) -> list[str]:
    errs = []
    for k in (
        "session_id",
        "audio_sha256",
        "split",
        "condition",
        "method",
        "status",
        "seed",
        "notes",
    ):
        if k not in ref:
            errs.append(f"{name}: missing '{k}' (required; nothing is inferred)")
    if ref.get("split") not in ("dev", "holdout"):
        errs.append(f"{name}: split must be dev or holdout")
    if ref.get("condition") not in MINIMUMS:
        errs.append(f"{name}: condition must be one of {sorted(MINIMUMS)}")
    if ref.get("method") not in ("manual", "score"):
        errs.append(f"{name}: method must be manual or score")
    if "status" in ref and ref["status"] != "final":
        errs.append(f"{name}: annotation is not finalized (status {ref['status']!r})")
    seed = ref.get("seed")
    if "seed" in ref and not (seed == "blank" or is_engine_seed(seed)):
        errs.append(f"{name}: seed must be 'blank' or 'transcription:...', got {seed!r}")
    notes = ref.get("notes") or []
    if not notes:
        errs.append(f"{name}: no reference notes")
    for i, n in enumerate(notes):
        if not (0 <= n["start"] < n["end"]) or not (0 <= int(n["midi"]) <= 127):
            errs.append(f"{name}: invalid note #{i} {n}")
    return errs


def check_duplicates(refs: list[tuple[str, dict]]) -> list[str]:
    """Each recording may appear once: no repeated session ids or audio hashes, across splits."""
    errs, seen_sid, seen_sha = [], {}, {}
    for name, ref in refs:
        for key, seen, label in (
            (ref.get("session_id"), seen_sid, "session"),
            (ref.get("audio_sha256"), seen_sha, "audio sha256"),
        ):
            if key in seen:
                errs.append(f"{name}: duplicate {label} also used by {seen[key]}")
            elif key:
                seen[key] = name
    return errs


def fingerprint(clips: list[dict]) -> str:
    """Content hash of everything that determines a score (ids, splits, refs, audio)."""
    canon = [
        {"id": c["id"], "split": c["split"], "notes": c["notes"], "tags": c["tags"]}
        for c in sorted(clips, key=lambda c: c["id"])
    ]
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode()).hexdigest()


def prepare(args) -> int:
    import soundfile as sf
    from jamrecall.audio import decode_mono  # the app's own decoder (backend venv)

    data_dir = Path(args.data_dir).resolve()
    refs_dir = BENCH / args.tag / "references" if args.refs is None else Path(args.refs)
    manifest_path = CORPUS / args.tag / "manifest.json"
    manifest_path.unlink(missing_ok=True)  # never leave a stale manifest behind
    paths = sorted(refs_dir.glob("*.json"))
    if not paths:
        print(f"no reference files in {refs_dir}")
        return 2
    refs = [(p.stem, json.loads(p.read_text())) for p in paths]
    errors = check_duplicates(refs)
    conn = sqlite3.connect(data_dir / "jamrecall.sqlite3")
    clips = []
    for name, ref in refs:
        errs = validate_reference(ref, name)
        row = conn.execute(
            "SELECT audio_path, audio_sha256 FROM sessions WHERE id = ?", (ref.get("session_id"),)
        ).fetchone()
        if row is None:
            errs.append(f"{name}: session {ref.get('session_id')} not in {data_dir}")
        if errs:
            errors += errs
            continue
        audio_path = data_dir / row[0]
        digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()
        if not (digest == row[1] == ref["audio_sha256"]):
            errors.append(
                f"{name}: sha256 mismatch (file {digest[:12]}, db {row[1][:12]}, "
                f"reference {ref['audio_sha256'][:12]})"
            )
            continue
        buf = decode_mono(audio_path, 22050)
        late = [n for n in ref["notes"] if n["end"] > buf.duration_seconds + 0.001]
        if late:
            errors.append(
                f"{name}: {len(late)} reference note(s) end after the recording "
                f"({buf.duration_seconds:.3f} s)"
            )
            continue
        out = CORPUS / args.tag / ref["split"] / f"{name}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(out, buf.samples, buf.sample_rate, subtype="FLOAT")
        clips.append(
            {
                "id": name,
                "split": ref["split"],
                "audio": str(out.relative_to(CORPUS)),
                "duration": round(buf.duration_seconds, 6),
                "notes": [
                    {
                        "start": float(n["start"]),
                        "end": float(n["end"]),
                        "midi": int(n["midi"]),
                        "technique": n.get("technique"),
                    }
                    for n in ref["notes"]
                ],
                "tags": {
                    "condition": ref["condition"],
                    "method": ref["method"],
                    "seed": ref["seed"],
                    "revision": ref.get("revision"),
                    "session_id": ref["session_id"],
                    "audio_sha256": digest,
                },
            }
        )
    if errors:
        for e in errors:
            print("ERROR", e)
        print("No manifest written: fix the references above and run prepare again.")
        return 1
    write_json(
        manifest_path, {"corpus": args.tag, "fingerprint": fingerprint(clips), "clips": clips}
    )
    for (cond, split), n in sorted(counts(clips).items()):
        print(f"condition {cond} {split}: {n['recordings']} recordings, {n['notes']} notes")
    return 0


def counts(clips: list[dict]) -> dict:
    """Recordings/notes that count toward the minimums (engine-seeded holdout refs excluded)."""
    c: dict = defaultdict(lambda: {"recordings": 0, "notes": 0})
    for clip in clips:
        if clip["split"] == "holdout" and is_engine_seed(clip["tags"].get("seed")):
            continue
        k = (clip["tags"]["condition"], clip["split"])
        c[k]["recordings"] += 1
        c[k]["notes"] += len(clip["notes"])
    return c


# --- scoring ------------------------------------------------------------------------------------


def without_technique_notes(ref: list[dict], est: list[dict]) -> tuple[list[dict], list[dict]]:
    """Drop technique-tagged reference notes *and* the estimates matched to them (nearest onset
    within the onset tolerance), so detected technique notes are not counted as false positives."""
    tagged = [n for n in ref if n.get("technique")]
    plain = [n for n in ref if not n.get("technique")]
    remaining = list(est)
    for t in tagged:
        near = [e for e in remaining if abs(e["start"] - t["start"]) <= ONSET_TOL]
        if near:
            remaining.remove(min(near, key=lambda e: abs(e["start"] - t["start"])))
    return plain, remaining


def score(args) -> int:
    from jamrecall_bench.methods import FMAX, FMIN, METHODS, grid

    analyse, to_notes, spec = METHODS[args.method]
    manifest_path = CORPUS / args.tag / "manifest.json"
    if not manifest_path.exists():
        print(f"no manifest at {manifest_path}: run prepare first (it writes none on errors)")
        return 2
    manifest = read_json(manifest_path)
    clips = manifest["clips"]
    if args.method == "basic-pitch":
        app = app_bp_params()
        if (app["min_freq_hz"], app["max_freq_hz"]) != (FMIN, FMAX):
            print("bench frequency range differs from the app's; refusing to score")
            return 1
        params = {k: app[k] for k in BENCH_BP_KEYS}
    else:
        params = read_json(RESULTS / f"{args.method}.json")["selected_params"] if spec else {}
    feats, timing = {}, {}
    for c in clips:
        t0 = time.perf_counter()
        feats[c["id"]] = analyse(CORPUS / c["audio"])
        timing[c["id"]] = time.perf_counter() - t0
    tuned = None
    if args.tune_on_dev and spec:
        dev = [c for c in clips if c["split"] == "dev"]  # never holdout
        best = max(
            grid(spec),
            key=lambda p: aggregate(
                [clip_stats(c["notes"], to_notes(feats[c["id"]], p)) for c in dev]
            )["onset"]["f1"],
        )
        tuned, params = best, best

    per_rec, groups, excluded = {}, defaultdict(list), []
    for c in clips:
        t0 = time.perf_counter()
        est = to_notes(feats[c["id"]], params)
        proc = timing[c["id"]] + time.perf_counter() - t0
        s = clip_stats(c["notes"], est)
        plain_ref, plain_est = without_technique_notes(c["notes"], est)
        s_plain = clip_stats(plain_ref, plain_est) if plain_ref else None
        cond, split = c["tags"]["condition"], c["split"]
        per_rec[c["id"]] = aggregate([s]) | {
            "split": split,
            "condition": cond,
            "duration_s": c["duration"],
            "processing_s": round(proc, 3),
            "real_time_factor": round(proc / c["duration"], 4),
        }
        if split == "holdout" and is_engine_seed(c["tags"].get("seed")):
            # Protocol: a holdout reference seeded from engine output is not independent evidence.
            per_rec[c["id"]]["excluded_from_holdout"] = "reference seeded from engine output"
            excluded.append(c["id"])
            continue
        groups[(split, cond)].append((s, s_plain))
        if cond in GATING:
            groups[(split, "A+B+C")].append((s, s_plain))
    summary = {}
    for (split, cond), v in sorted(groups.items()):
        plain = [p for _, p in v if p is not None]
        summary[f"{split}/{cond}"] = aggregate([s for s, _ in v]) | {
            "excluding_technique_notes": aggregate(plain)["onset"] if plain else None
        }
    out = {
        "method": args.method,
        "params": params,
        "tuned_on_real_dev": tuned,
        "manifest_fingerprint": manifest["fingerprint"],
        "scored_clip_ids": sorted(c["id"] for c in clips),
        "excluded_holdout_engine_seeded": excluded,
        "per_recording": per_rec,
        "summary": summary,
    }
    write_json(results_dir(args.tag) / f"real-{args.method}.json", out)
    for k, v in summary.items():
        print(
            f"  {k:18s} onset P {v['onset']['precision']:.3f} R {v['onset']['recall']:.3f} "
            f"F1 {v['onset']['f1']:.3f}  pitch exact {v['pitch_on_onset_matched']['exact']:.3f}"
            f"  +offset F1 {v['onset_offset']['f1']:.3f}"
        )
    return 0


# --- gate ---------------------------------------------------------------------------------------


def evaluate_gate(manifest: dict, bp: dict, py: dict, app_params: dict) -> dict:
    """Pure gate decision. INCOMPLETE whenever the evidence is missing, stale or not the app's."""
    clips = manifest["clips"]
    problems: list[str] = []
    ids = sorted(c["id"] for c in clips)
    current = fingerprint(clips)
    if manifest.get("fingerprint") != current:
        problems.append("manifest fingerprint does not match its contents")
    for name, r in (("basic-pitch", bp), ("pyin", py)):
        if r.get("manifest_fingerprint") != current:
            problems.append(f"{name} results were scored on a different manifest; re-run score")
        if r.get("scored_clip_ids") != ids:
            problems.append(f"{name} results do not cover exactly the manifest's recordings")
    if bp.get("tuned_on_real_dev") is not None:
        problems.append(
            "basic-pitch was re-tuned on dev; the app does not run those parameters "
            "(integrate them through a decision request, then re-score untuned)"
        )
    if bp.get("params") != {k: app_params[k] for k in BENCH_BP_KEYS}:
        problems.append("basic-pitch was scored with parameters other than the app's")

    c = counts(clips)
    below = []
    for cond, (n_dev, n_hold, n_notes) in MINIMUMS.items():
        dev, hold = c.get((cond, "dev"), {}), c.get((cond, "holdout"), {})
        if (
            dev.get("recordings", 0) < n_dev
            or hold.get("recordings", 0) < n_hold
            or hold.get("notes", 0) < n_notes
        ):
            below.append(cond)
    gating_below = [x for x in below if x in GATING]

    checks, poor, missing_summaries = {}, [], []
    for cond in (*GATING, "A+B+C"):
        for name, r in (("basic-pitch", bp), ("pyin", py)):
            if f"holdout/{cond}" not in r.get("summary", {}):
                missing_summaries.append(f"{name}:holdout/{cond}")
    if not missing_summaries:
        f_bp = bp["summary"]["holdout/A+B+C"]["onset"]["f1"]
        f_py = py["summary"]["holdout/A+B+C"]["onset"]["f1"]
        checks[f"basic_pitch_onset_f1 >= {GATE_F1}"] = [f_bp, f_bp >= GATE_F1]
        checks["basic_pitch_onset_f1 >= pyin_onset_f1"] = [[f_bp, f_py], f_bp >= f_py]
        for cond in GATING:
            s = bp["summary"][f"holdout/{cond}"]
            f1, exact = s["onset"]["f1"], s["pitch_on_onset_matched"]["exact"]
            checks[f"condition {cond}: onset F1 >= {POOR_F1}"] = [f1, f1 >= POOR_F1]
            checks[f"condition {cond}: pitch exact >= {POOR_PITCH}"] = [exact, exact >= POOR_PITCH]
            if f1 < POOR_F1 or exact < POOR_PITCH:
                poor.append(cond)

    if problems or gating_below or missing_summaries:
        verdict = "INCOMPLETE"
    elif all(ok for _, ok in checks.values()):
        verdict = "PASS"
    else:
        verdict = "FAIL"
    return {
        "verdict": verdict,
        "checks": checks,
        "poor_conditions": poor,
        "integrity_problems": problems,
        "missing_summaries": missing_summaries,
        "conditions_below_minimum": below,
        "excluded_holdout_engine_seeded": bp.get("excluded_holdout_engine_seeded", []),
        "exploratory_D": (bp.get("summary", {}).get("holdout/D") or {}).get("onset"),
        "manifest_fingerprint": current,
        "thresholds": {
            "gate_f1": GATE_F1,
            "condition_min_onset_f1": POOR_F1,
            "condition_min_pitch_exact": POOR_PITCH,
        },
    }


def gate(args) -> int:
    d = results_dir(args.tag)
    try:
        manifest = read_json(CORPUS / args.tag / "manifest.json")
        bp, py = read_json(d / "real-basic-pitch.json"), read_json(d / "real-pyin.json")
    except FileNotFoundError as exc:
        print(f"INCOMPLETE: {exc.filename} missing (run prepare and score for both engines)")
        return 2
    result = evaluate_gate(manifest, bp, py, app_bp_params())
    write_json(d / "real-gate.json", result)
    print(json.dumps(result, indent=1))
    return {"PASS": 0, "FAIL": 1, "INCOMPLETE": 2}[result["verdict"]]


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
