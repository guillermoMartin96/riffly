"""Integrity of the real-recording gate (Codex interim review findings 1, 2, 7, 8, 10)."""

import copy
import json
from argparse import Namespace

import numpy as np
import pytest
import soundfile as sf

from jamrecall_bench import real
from jamrecall_bench.score import aggregate, clip_stats

APP = real.app_bp_params()
BP_PARAMS = {k: APP[k] for k in real.BENCH_BP_KEYS}


def ref(**kw):
    base = {
        "session_id": "s1",
        "audio_sha256": "a" * 64,
        "split": "dev",
        "condition": "A",
        "method": "manual",
        "status": "final",
        "seed": "blank",
        "notes": [{"start": 0.1, "end": 0.3, "midi": 60}],
    }
    return base | kw


def test_reference_requires_explicit_status_and_seed():
    r = ref()
    del r["status"], r["seed"]
    errs = real.validate_reference(r, "x")
    assert any("'status'" in e for e in errs) and any("'seed'" in e for e in errs)
    assert real.validate_reference(ref(status="draft"), "x")
    assert real.validate_reference(ref(seed="copied"), "x")
    assert real.validate_reference(ref(seed="transcription:abc:basic-pitch@0.4.0"), "x") == []


def test_duplicates_refused_across_splits():
    errs = real.check_duplicates([("a", ref()), ("b", ref(split="holdout"))])
    assert any("duplicate session" in e for e in errs)
    errs = real.check_duplicates([("a", ref()), ("b", ref(session_id="s2"))])
    assert any("duplicate audio sha256" in e for e in errs)
    assert (
        real.check_duplicates([("a", ref()), ("b", ref(session_id="s2", audio_sha256="b" * 64))])
        == []
    )


def test_technique_exclusion_drops_matched_estimates():
    ref_notes = [
        {"start": 0.1, "end": 0.3, "midi": 60},
        {"start": 0.5, "end": 0.8, "midi": 62, "technique": "bend"},
    ]
    est = [{"start": 0.1, "end": 0.3, "midi": 60}, {"start": 0.51, "end": 0.8, "midi": 62}]
    plain_ref, plain_est = real.without_technique_notes(ref_notes, est)
    assert aggregate([clip_stats(plain_ref, plain_est)])["onset"]["f1"] == 1.0


# --- gate ---------------------------------------------------------------------------------------


def clip(cid, split, cond, seed="blank", n=20):
    notes = [
        {"start": i * 0.5, "end": i * 0.5 + 0.4, "midi": 60, "technique": None} for i in range(n)
    ]
    return {
        "id": cid,
        "split": split,
        "audio": f"x/{cid}.wav",
        "duration": n * 0.5,
        "notes": notes,
        "tags": {
            "condition": cond,
            "method": "manual",
            "seed": seed,
            "revision": 1,
            "session_id": cid,
            "audio_sha256": cid,
        },
    }


def full_manifest():
    clips = [
        clip(f"{c}-{s}{i}", s, c)
        for c in "ABC"
        for s, k in (("dev", 2), ("holdout", 3))
        for i in range(k)
    ]
    return {"clips": clips, "fingerprint": real.fingerprint(clips)}


def summary_entry(f1, exact=1.0):
    return {
        "onset": {"precision": f1, "recall": f1, "f1": f1},
        "onset_offset": {"f1": f1},
        "pitch_on_onset_matched": {"exact": exact},
    }


def results(manifest, f1=0.9, per_cond=None, params=BP_PARAMS, tuned=None):
    summary = {
        f"holdout/{c}": summary_entry(*(per_cond or {}).get(c, (f1,))) for c in ("A", "B", "C")
    }
    summary["holdout/A+B+C"] = summary_entry(f1)
    return {
        "params": params,
        "tuned_on_real_dev": tuned,
        "manifest_fingerprint": manifest["fingerprint"],
        "scored_clip_ids": sorted(c["id"] for c in manifest["clips"]),
        "summary": summary,
    }


def test_gate_passes_only_with_complete_matching_evidence():
    m = full_manifest()
    g = real.evaluate_gate(m, results(m, 0.9), results(m, 0.8, params={}), APP)
    assert g["verdict"] == "PASS", g


def test_gate_refuses_stale_results():
    m = full_manifest()
    bp, py = results(m, 0.9), results(m, 0.8, params={})
    m2 = copy.deepcopy(m)
    m2["clips"][0]["notes"][0]["midi"] = 61  # a reference changed after scoring
    m2["fingerprint"] = real.fingerprint(m2["clips"])
    g = real.evaluate_gate(m2, bp, py, APP)
    assert g["verdict"] == "INCOMPLETE"
    assert any("different manifest" in p for p in g["integrity_problems"])


def test_gate_refuses_missing_condition_summaries():
    m = full_manifest()
    bp = results(m, 0.95)
    bp["summary"] = {"holdout/A+B+C": summary_entry(0.95)}  # no per-condition results
    g = real.evaluate_gate(m, bp, results(m, 0.5, params={}), APP)
    assert g["verdict"] == "INCOMPLETE" and g["missing_summaries"]


def test_gate_refuses_params_other_than_the_apps():
    m = full_manifest()
    py = results(m, 0.5, params={})
    tuned = results(m, 0.95, tuned={"onset_thresh": 0.3})
    assert real.evaluate_gate(m, tuned, py, APP)["verdict"] == "INCOMPLETE"
    other = results(m, 0.95, params=BP_PARAMS | {"onset_thresh": 0.3})
    assert real.evaluate_gate(m, other, py, APP)["verdict"] == "INCOMPLETE"


def test_gate_fails_on_poor_condition_or_losing_to_pyin():
    m = full_manifest()
    py = results(m, 0.5, params={})
    poor = results(m, 0.9, per_cond={"B": (0.65,)})
    g = real.evaluate_gate(m, poor, py, APP)
    assert g["verdict"] == "FAIL" and g["poor_conditions"] == ["B"]
    bad_pitch = results(m, 0.9, per_cond={"C": (0.9, 0.85)})
    assert real.evaluate_gate(m, bad_pitch, py, APP)["poor_conditions"] == ["C"]
    assert (
        real.evaluate_gate(m, results(m, 0.85), results(m, 0.9, params={}), APP)["verdict"]
        == "FAIL"
    )


def test_engine_seeded_holdout_does_not_count_toward_minimums():
    m = full_manifest()
    m["clips"][2]["tags"]["seed"] = "transcription:x:basic-pitch@0.4.0"  # an A holdout clip
    m["fingerprint"] = real.fingerprint(m["clips"])
    g = real.evaluate_gate(m, results(m, 0.9), results(m, 0.8, params={}), APP)
    assert g["verdict"] == "INCOMPLETE" and "A" in g["conditions_below_minimum"]


# --- prepare end to end ---------------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path):
    from jamrecall import store
    from jamrecall.db import migrate, transaction

    d = tmp_path / "var"
    migrate(d / "jamrecall.sqlite3")
    sids = []
    for i in range(2):
        audio = (0.3 * np.sin(2 * np.pi * 220 * np.arange(22050) / 22050)).astype(np.float32)
        path = d / "media" / "sessions" / f"s{i}" / "original.wav"
        path.parent.mkdir(parents=True)
        sf.write(path, audio * (i + 1) / 2, 22050)
        import hashlib

        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        with transaction(d / "jamrecall.sqlite3") as conn:
            store.insert_session(
                conn,
                id=f"s{i}",
                audio_path=f"media/sessions/s{i}/original.wav",
                audio_mime="audio/wav",
                audio_bytes=path.stat().st_size,
                audio_sha256=sha,
                duration_seconds=1.0,
                sample_rate=22050,
                created_at="t",
            )
        sids.append((f"s{i}", sha))
    return d, sids


def write_refs(folder, refs):
    folder.mkdir(parents=True, exist_ok=True)
    for name, r in refs.items():
        (folder / f"{name}.json").write_text(json.dumps(r))


def test_prepare_writes_fingerprinted_manifest(tmp_path, data_dir, monkeypatch):
    monkeypatch.setattr(real, "CORPUS", tmp_path / "corpus")
    d, sids = data_dir
    write_refs(
        tmp_path / "refs",
        {
            "one": ref(session_id=sids[0][0], audio_sha256=sids[0][1]),
            "two": ref(session_id=sids[1][0], audio_sha256=sids[1][1], split="holdout"),
        },
    )
    args = Namespace(tag="t", data_dir=str(d), refs=str(tmp_path / "refs"))
    assert real.prepare(args) == 0
    m = json.loads((tmp_path / "corpus" / "t" / "manifest.json").read_text())
    assert m["fingerprint"] == real.fingerprint(m["clips"]) and len(m["clips"]) == 2


def test_prepare_refuses_duplicates_and_leaves_no_manifest(tmp_path, data_dir, monkeypatch):
    monkeypatch.setattr(real, "CORPUS", tmp_path / "corpus")
    d, sids = data_dir
    good = ref(session_id=sids[0][0], audio_sha256=sids[0][1])
    write_refs(tmp_path / "refs", {"one": good, "copy": good | {"split": "holdout"}})
    args = Namespace(tag="t", data_dir=str(d), refs=str(tmp_path / "refs"))
    assert real.prepare(args) == 1
    assert not (tmp_path / "corpus" / "t" / "manifest.json").exists()


def test_prepare_refuses_notes_beyond_the_recording(tmp_path, data_dir, monkeypatch):
    monkeypatch.setattr(real, "CORPUS", tmp_path / "corpus")
    d, sids = data_dir
    late = ref(
        session_id=sids[0][0],
        audio_sha256=sids[0][1],
        notes=[{"start": 0.5, "end": 1.5, "midi": 60}],
    )  # recording is 1.0 s
    write_refs(tmp_path / "refs", {"late": late})
    args = Namespace(tag="t", data_dir=str(d), refs=str(tmp_path / "refs"))
    assert real.prepare(args) == 1
