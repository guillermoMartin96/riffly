"""Real-recording validation gate (docs/research/real-recording-validation-protocol.md).

Authoritative and self-contained: `validate` reads the finalized reference annotations and the
contamination provenance **directly from the app database**, verifies each original recording
against its stored hashes, decodes it with the app's own decoder, runs Basic Pitch (the app's
parameters) and pYIN in the same process, scores both, applies the approved criteria, and writes a
report. It never reads back intermediate files (reference JSON, manifests, score results), so
editing such files cannot influence the verdict.

Run from bench/ with the backend venv (it has the app decoder, Basic Pitch, librosa and mir_eval):
  ../backend/.venv/bin/python -m jamrecall_bench.real validate --data-dir ../var
  ../backend/.venv/bin/python -m jamrecall_bench.real tune-dev --data-dir ../var  # informational

Exit codes: 0 PASS, 1 FAIL, 2 INCOMPLETE. The report goes to bench/results/real-validation.json
(or --out). Holdout eligibility comes from `jamrecall.provenance.status` (the same function the
app uses) plus dataset-level checks; any unknown or inconsistent provenance fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from jamrecall_bench.common import BENCH, RESULTS, read_json, write_json
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
SR = 22050


def is_engine_seed(seed: str | None) -> bool:
    return bool(seed) and seed.startswith("transcription:")


def app_bp_params() -> dict:
    data = json.loads(APP_PARAMS_FILE.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def fingerprint(clips: list[dict]) -> str:
    """Record of exactly what was evaluated (ids, splits, references, audio identities)."""
    keys = (
        "id",
        "session_id",
        "split",
        "condition",
        "seed",
        "revision",
        "audio_sha256",
        "pcm_sha256",
        "notes",
    )
    canon = [{k: c.get(k) for k in keys} for c in sorted(clips, key=lambda c: c["id"])]
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode()).hexdigest()


# --- dataset from the app database ----------------------------------------------------------------


def read_snapshot(db_path: Path) -> tuple[list[dict], list[str]]:
    """Every finalized reference with its provenance, read in ONE consistent database snapshot.

    Returns (records, problems). No audio is touched here.
    """
    if not db_path.exists():
        return [], [f"no app database at {db_path}"]
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")  # a single read transaction: all reads see the same snapshot
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"provenance_baseline", "seen_audio", "contaminated_audio"} <= tables:
            return [], ["app database predates contamination tracking (start the app to migrate)"]
        base = conn.execute("SELECT status, created_at_schema FROM provenance_baseline").fetchone()
        if base is None or base["status"] != "complete":
            return [], [
                "this data directory existed before full contamination tracking "
                f"(baseline: {dict(base) if base else 'missing'}); record the validation dataset "
                "in a fresh data directory (see the manual-testing guide)"
            ]
        records = []
        for r in conn.execute(
            """SELECT s.*, a.id AS annotation_id, a.split, a.condition, a.method, a.seed,
                      a.revision, a.finalized_at, a.annotator
               FROM sessions s JOIN annotations a ON a.session_id = s.id
               WHERE a.status = 'final' ORDER BY s.created_at"""
        ).fetchall():
            row = dict(r)
            row["notes"] = [
                {
                    "start": n["start_seconds"],
                    "end": n["end_seconds"],
                    "midi": n["midi_pitch"],
                    "technique": n["technique"],
                }
                for n in conn.execute(
                    "SELECT * FROM annotation_notes WHERE annotation_id = ? "
                    "ORDER BY start_seconds, id",
                    (row["annotation_id"],),
                )
            ]
            row["tombstoned"] = (
                conn.execute(
                    "SELECT 1 FROM contaminated_audio WHERE audio_sha256 = ?",
                    (row["audio_sha256"],),
                ).fetchone()
                is not None
            )
            records.append(row)
        conn.execute("COMMIT")
        return records, []
    finally:
        conn.close()


def snapshot_digest(records: list[dict]) -> str:
    return hashlib.sha256(json.dumps(records, sort_keys=True, default=str).encode()).hexdigest()


def load_dataset(data_dir: Path) -> tuple[list[dict], list[str], str]:
    """Finalized references with audio and provenance, straight from the app database.

    Returns (clips, problems, snapshot digest). Problems are integrity failures that make the
    verdict INCOMPLETE. References and provenance come from one snapshot, so they are consistent.
    """
    from jamrecall import provenance
    from jamrecall.audio import decode_mono

    records, problems = read_snapshot(data_dir / "jamrecall.sqlite3")
    clips: list[dict] = []
    for row in records:
        cid = f"{row['condition']}-{row['split']}-{row['id'][:8]}"
        if row["split"] not in ("dev", "holdout") or row["condition"] not in MINIMUMS:
            problems.append(f"{cid}: finalized without a valid split/condition")
            continue
        path = data_dir / row["audio_path"]
        if not path.is_file():
            problems.append(f"{cid}: original recording missing")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["audio_sha256"]:
            problems.append(f"{cid}: original recording does not match its stored sha256")
            continue
        buf = decode_mono(path, SR)
        pcm = hashlib.sha256(buf.samples.tobytes()).hexdigest()
        if pcm != row.get("pcm_sha256"):
            problems.append(f"{cid}: decoded audio differs from the hash stored at upload")
            continue
        notes = row["notes"]
        if not notes or any(n["end"] > buf.duration_seconds + 0.001 for n in notes):
            problems.append(f"{cid}: reference notes empty or past the end of the audio")
            continue
        prov = provenance.status(row)
        if row["tombstoned"] and prov["holdout_eligible"]:
            prov = prov | {
                "holdout_eligible": False,
                "ineligible_reason": "audio recorded as contaminated",
            }
        clips.append(
            {
                "id": cid,
                "session_id": row["id"],
                "split": row["split"],
                "condition": row["condition"],
                "method": row["method"],
                "seed": row["seed"],
                "revision": row["revision"],
                "finalized_at": row["finalized_at"],
                "annotator": row["annotator"],
                "audio_sha256": row["audio_sha256"],
                "pcm_sha256": pcm,
                "duration": buf.duration_seconds,
                "notes": notes,
                "provenance": prov,
                "samples": buf.samples,
            }
        )
    mark_duplicates(clips)
    return clips, problems, snapshot_digest(records)


def mark_duplicates(clips: list[dict]) -> None:
    """Audio appearing more than once in the dataset is not independent: flag every copy."""
    seen: dict[str, set[str]] = defaultdict(set)
    for c in clips:
        for h in {c["audio_sha256"], c["pcm_sha256"]}:
            seen[h].add(c["id"])
    dup_ids = {i for ids in seen.values() if len(ids) > 1 for i in ids}
    for c in clips:
        if c["id"] in dup_ids:
            c["duplicate"] = True


def holdout_exclusion(clip: dict) -> list[str]:
    """Why a holdout recording may not count (empty = eligible). Dev recordings: always []."""
    if clip["split"] != "holdout":
        return []
    reasons = []
    prov = clip.get("provenance")
    if is_engine_seed(clip.get("seed")):
        reasons.append("reference seeded from engine output")
    if not prov:
        reasons.append("provenance unknown (fail closed)")
    else:
        if not prov.get("holdout_eligible"):
            reasons.append(f"not holdout-eligible: {prov.get('ineligible_reason')}")
        exposed, final = prov.get("model_exposed_at"), clip.get("finalized_at")
        if exposed and (not final or exposed < final):
            reasons.append("model output requested before the latest finalization")
    if clip.get("duplicate"):
        reasons.append("audio appears more than once in the dataset")
    return reasons


def counts(clips: list[dict]) -> dict:
    """Recordings/notes that count toward the minimums (ineligible holdout recordings excluded)."""
    c: dict = defaultdict(lambda: {"recordings": 0, "notes": 0})
    for clip in clips:
        if holdout_exclusion(clip):
            continue
        k = (clip["condition"], clip["split"])
        c[k]["recordings"] += 1
        c[k]["notes"] += len(clip["notes"])
    return c


# --- scoring ------------------------------------------------------------------------------------


def without_technique_notes(ref: list[dict], est: list[dict]) -> tuple[list[dict], list[dict]]:
    """Drop technique-tagged reference notes *and* the estimates the scorer matches to them.

    Uses the same optimal onset+pitch matching as the main score (mir_eval), so an estimate that
    matches a plain note is never removed.
    """
    import mir_eval
    import numpy as np

    tagged_idx = {i for i, n in enumerate(ref) if n.get("technique")}
    plain = [n for i, n in enumerate(ref) if i not in tagged_idx]
    if not tagged_idx or not est:
        return plain, list(est)

    def arrays(notes: list[dict]):
        iv = np.array([[n["start"], n["end"]] for n in notes], dtype=float)
        hz = mir_eval.util.midi_to_hz(np.array([n["midi"] for n in notes], dtype=float))
        return iv, hz

    r_iv, r_hz = arrays(ref)
    e_iv, e_hz = arrays(est)
    pairs = mir_eval.transcription.match_notes(
        r_iv, r_hz, e_iv, e_hz, onset_tolerance=ONSET_TOL, pitch_tolerance=50.0, offset_ratio=None
    )
    drop = {j for i, j in pairs if i in tagged_idx}
    return plain, [e for j, e in enumerate(est) if j not in drop]


def engine_params(method: str) -> dict:
    if method == "basic-pitch":
        from jamrecall_bench.methods import FMAX, FMIN

        app = app_bp_params()
        if (app["min_freq_hz"], app["max_freq_hz"]) != (FMIN, FMAX):
            raise SystemExit("bench frequency range differs from the app's; refusing to score")
        return {k: app[k] for k in BENCH_BP_KEYS}
    return read_json(RESULTS / f"{method}.json")["selected_params"]


def analyse_all(method: str, clips: list[dict]) -> tuple[dict, dict]:
    """Run an engine's analysis on every clip's decoded samples (written to a private temp dir)."""
    import soundfile as sf

    from jamrecall_bench.methods import METHODS

    analyse = METHODS[method][0]
    feats, secs = {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        for c in clips:
            wav = Path(tmp) / f"{c['id']}.wav"
            sf.write(wav, c["samples"], SR, subtype="FLOAT")
            t0 = time.perf_counter()
            feats[c["id"]] = analyse(wav)
            secs[c["id"]] = time.perf_counter() - t0
    return feats, secs


def score_engine(method: str, clips: list[dict], feats: dict, secs: dict, params: dict) -> dict:
    from jamrecall_bench.methods import METHODS

    to_notes = METHODS[method][1]
    per_rec, groups = {}, defaultdict(list)
    for c in clips:
        t0 = time.perf_counter()
        est = to_notes(feats[c["id"]], params)
        proc = secs[c["id"]] + time.perf_counter() - t0
        per_rec[c["id"]], s, s_plain = score_clip(c, est, proc)
        if per_rec[c["id"]]["excluded_from_holdout"]:
            continue
        groups[(c["split"], c["condition"])].append((s, s_plain))
        if c["condition"] in GATING:
            groups[(c["split"], "A+B+C")].append((s, s_plain))
    return {
        "method": method,
        "params": params,
        "per_recording": per_rec,
        "summary": summarize(groups),
    }


def score_clip(c: dict, est: list[dict], proc: float):
    s = clip_stats(c["notes"], est)
    plain_ref, plain_est = without_technique_notes(c["notes"], est)
    s_plain = clip_stats(plain_ref, plain_est) if plain_ref else None
    rec = aggregate([s]) | {
        "split": c["split"],
        "condition": c["condition"],
        "duration_s": round(c["duration"], 3),
        "processing_s": round(proc, 3),
        "real_time_factor": round(proc / c["duration"], 4),
        "excluded_from_holdout": holdout_exclusion(c) or None,
    }
    return rec, s, s_plain


def summarize(groups: dict) -> dict:
    summary = {}
    for (split, cond), v in sorted(groups.items()):
        plain = [p for _, p in v if p is not None]
        summary[f"{split}/{cond}"] = aggregate([s for s, _ in v]) | {
            "excluding_technique_notes": aggregate(plain)["onset"] if plain else None
        }
    return summary


# --- decision -----------------------------------------------------------------------------------


def decide(clips: list[dict], bp: dict, py: dict, problems: list[str]) -> dict:
    """Pure gate decision from scores computed in this run. Thresholds and minimums unchanged."""
    excluded = [{"id": c["id"], "reasons": r} for c in clips if (r := holdout_exclusion(c))]
    eligible = sorted(
        c["id"] for c in clips if c["split"] == "holdout" and not holdout_exclusion(c)
    )
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
    checks, poor, missing = {}, [], []
    for cond in (*GATING, "A+B+C"):
        for name, r in (("basic-pitch", bp), ("pyin", py)):
            if f"holdout/{cond}" not in r["summary"]:
                missing.append(f"{name}:holdout/{cond}")
    if not missing:
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
    if problems or gating_below or missing:
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
        "missing_summaries": missing,
        "conditions_below_minimum": below,
        "eligible_holdout": eligible,
        "excluded_holdout": excluded,
        "counts": {f"{k[0]}/{k[1]}": v for k, v in sorted(c.items())},
        "exploratory_D": (bp["summary"].get("holdout/D") or {}).get("onset"),
        "thresholds": {
            "gate_f1": GATE_F1,
            "condition_min_onset_f1": POOR_F1,
            "condition_min_pitch_exact": POOR_PITCH,
        },
    }


def run_validation(data_dir: Path) -> dict:
    clips, problems, digest = load_dataset(data_dir)
    results = {}
    for method in ("basic-pitch", "pyin"):
        feats, secs = analyse_all(method, clips)
        results[method] = score_engine(method, clips, feats, secs, engine_params(method))
    # Provenance only ever moves towards contamination and edits bump revisions, so any change
    # between the snapshot and the end of scoring is detectable here.
    after, _ = read_snapshot(data_dir / "jamrecall.sqlite3")
    if snapshot_digest(after) != digest:
        problems.append("references or provenance changed during validation; run again")
    report = decide(clips, results["basic-pitch"], results["pyin"], problems)
    report |= {
        "dataset_fingerprint": fingerprint(clips),
        "data_dir": str(data_dir),
        "app_basic_pitch_params": app_bp_params(),
        "recordings": [{k: v for k, v in c.items() if k != "samples"} for c in clips],
        "results": results,
    }
    return report


def validate(args) -> int:
    report = run_validation(Path(args.data_dir).resolve())
    out = Path(args.out) if args.out else RESULTS / "real-validation.json"
    write_json(out, report)
    print(f"VERDICT: {report['verdict']}")
    for k in ("integrity_problems", "conditions_below_minimum", "poor_conditions"):
        if report[k]:
            print(f"  {k}: {report[k]}")
    for e in report["excluded_holdout"]:
        print(f"  excluded {e['id']}: {'; '.join(e['reasons'])}")
    for name, r in report["results"].items():
        for key, v in r["summary"].items():
            print(
                f"  {name:11s} {key:16s} onset P {v['onset']['precision']:.3f} "
                f"R {v['onset']['recall']:.3f} F1 {v['onset']['f1']:.3f}  pitch exact "
                f"{v['pitch_on_onset_matched']['exact']:.3f}  +offset F1 "
                f"{v['onset_offset']['f1']:.3f}"
            )
    print(f"report: {out}")
    return {"PASS": 0, "FAIL": 1, "INCOMPLETE": 2}[report["verdict"]]


def tune_dev(args) -> int:
    """Informational: best parameters on the real DEV split only. Never used by `validate`;
    adopting them requires a decision request and an app change, then a fresh validation."""
    from jamrecall_bench.methods import METHODS, grid

    clips, problems, _ = load_dataset(Path(args.data_dir).resolve())
    dev = [c for c in clips if c["split"] == "dev"]
    report = {"dev_recordings": [c["id"] for c in dev], "problems": problems, "best": {}}
    for method in ("basic-pitch", "pyin"):
        _, to_notes, spec = METHODS[method]
        feats, _ = analyse_all(method, dev)
        report["best"][method] = max(
            grid(spec),
            key=lambda p: aggregate(
                [clip_stats(c["notes"], to_notes(feats[c["id"]], p)) for c in dev]
            )["onset"]["f1"],
        )
    write_json(RESULTS / "real-tune-dev.json", report)
    print(json.dumps(report, indent=1))
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--data-dir", required=True, help="app data directory (database + recordings)")
    v.add_argument("--out", default=None)
    t = sub.add_parser("tune-dev")
    t.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    sys.exit({"validate": validate, "tune-dev": tune_dev}[args.cmd](args))


if __name__ == "__main__":
    main()
