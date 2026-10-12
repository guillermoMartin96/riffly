"""Real-recording validation gate: integrity, contamination guard, decision logic."""

import io
import json
import sqlite3

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient

from jamrecall_bench import real
from jamrecall_bench.score import aggregate, clip_stats

CLEAN = {"holdout_eligible": True, "ineligible_reason": None, "model_exposed_at": None}


# --- helpers ------------------------------------------------------------------------------------


def clip(cid, split, cond, n=20, seed="blank", prov=None, finalized="2026-10-12T10:00:00Z"):
    notes = [
        {"start": i * 0.5, "end": i * 0.5 + 0.4, "midi": 60, "technique": None} for i in range(n)
    ]
    return {
        "id": cid,
        "session_id": cid,
        "split": split,
        "condition": cond,
        "seed": seed,
        "revision": 1,
        "finalized_at": finalized,
        "audio_sha256": f"a-{cid}",
        "pcm_sha256": f"p-{cid}",
        "duration": n * 0.5,
        "notes": notes,
        "provenance": dict(CLEAN) if prov is None else prov,
    }


def full_dataset():
    return [
        clip(f"{c}-{s}{i}", s, c)
        for c in "ABC"
        for s, k in (("dev", 2), ("holdout", 3))
        for i in range(k)
    ]


def entry(f1, exact=1.0):
    return {
        "onset": {"precision": f1, "recall": f1, "f1": f1},
        "onset_offset": {"f1": f1},
        "pitch_on_onset_matched": {"exact": exact},
    }


def scores(f1, per_cond=None):
    s = {f"holdout/{c}": entry(*(per_cond or {}).get(c, (f1,))) for c in "ABC"}
    s["holdout/A+B+C"] = entry(f1)
    return {"summary": s}


# --- exclusion rules ----------------------------------------------------------------------------


def test_exclusion_reasons():
    assert real.holdout_exclusion(clip("x", "holdout", "A")) == []
    assert real.holdout_exclusion(clip("x", "dev", "A", prov={})) == []  # dev never excluded
    r = real.holdout_exclusion(clip("x", "holdout", "A", seed="transcription:t:bp@1"))
    assert r == ["reference seeded from engine output"]
    r = real.holdout_exclusion(clip("x", "holdout", "A", prov={}))
    assert r == ["provenance unknown (fail closed)"]
    bad = {"holdout_eligible": False, "ineligible_reason": "contaminated", "model_exposed_at": None}
    assert real.holdout_exclusion(clip("x", "holdout", "A", prov=bad)) == [
        "not holdout-eligible: contaminated"
    ]
    early = dict(CLEAN, model_exposed_at="2026-10-12T09:00:00Z")  # before finalized_at
    assert real.holdout_exclusion(clip("x", "holdout", "A", prov=early)) == [
        "model output requested before the latest finalization"
    ]
    late = dict(CLEAN, model_exposed_at="2026-10-12T11:00:00Z")  # after finalization: fine
    assert real.holdout_exclusion(clip("x", "holdout", "A", prov=late)) == []


def test_duplicates_within_dataset_are_all_flagged():
    a, b, c = clip("a", "dev", "A"), clip("b", "holdout", "A"), clip("c", "holdout", "A")
    b["pcm_sha256"] = a["pcm_sha256"]  # same decoded audio, different container
    real.mark_duplicates([a, b, c])
    assert a.get("duplicate") and b.get("duplicate") and not c.get("duplicate")
    assert "audio appears more than once in the dataset" in real.holdout_exclusion(b)


# --- decision ------------------------------------------------------------------------------------


def test_pass_requires_all_criteria():
    d = full_dataset()
    g = real.decide(d, scores(0.9), scores(0.8), [])
    assert (
        g["verdict"] == "PASS" and len(g["eligible_holdout"]) == 9 and g["excluded_holdout"] == []
    )


def test_fail_on_poor_condition_pitch_or_pyin():
    d = full_dataset()
    assert real.decide(d, scores(0.9, {"B": (0.65,)}), scores(0.8), [])["poor_conditions"] == ["B"]
    assert real.decide(d, scores(0.9, {"C": (0.9, 0.85)}), scores(0.8), [])["verdict"] == "FAIL"
    assert real.decide(d, scores(0.85), scores(0.9), [])["verdict"] == "FAIL"
    assert real.decide(d, scores(0.79), scores(0.5), [])["verdict"] == "FAIL"


def test_contaminated_holdout_does_not_count_and_is_reported():
    d = full_dataset()
    victim = next(c for c in d if c["split"] == "holdout" and c["condition"] == "B")
    victim["provenance"] = {
        "holdout_eligible": False,
        "model_exposed_at": "x",
        "ineligible_reason": "transcription requested before the reference "
        "annotation was finalized",
    }
    g = real.decide(d, scores(0.9), scores(0.8), [])
    assert g["verdict"] == "INCOMPLETE" and "B" in g["conditions_below_minimum"]
    assert [e["id"] for e in g["excluded_holdout"]] == [victim["id"]]
    assert victim["id"] not in g["eligible_holdout"]


def test_integrity_problems_or_missing_summaries_are_incomplete():
    d = full_dataset()
    assert real.decide(d, scores(0.9), scores(0.8), ["x"])["verdict"] == "INCOMPLETE"
    bp = scores(0.9)
    del bp["summary"]["holdout/C"]
    assert real.decide(d, bp, scores(0.8), [])["verdict"] == "INCOMPLETE"


def test_contaminated_dev_recordings_are_fine():
    d = full_dataset()
    for c in d:
        if c["split"] == "dev":
            c["provenance"] = {"holdout_eligible": False, "ineligible_reason": "x"}
    assert real.decide(d, scores(0.9), scores(0.8), [])["verdict"] == "PASS"


def test_thresholds_and_minimums_unchanged():
    assert (real.GATE_F1, real.POOR_F1, real.POOR_PITCH) == (0.80, 0.70, 0.90)
    assert real.MINIMUMS == {"A": (2, 3, 60), "B": (2, 3, 60), "C": (2, 3, 60), "D": (1, 2, 0)}


def test_technique_exclusion_drops_only_matched_estimates():
    ref = [
        {"start": 0.1, "end": 0.3, "midi": 60},
        {"start": 0.5, "end": 0.8, "midi": 62, "technique": "bend"},
    ]
    est = [{"start": 0.1, "end": 0.3, "midi": 60}, {"start": 0.51, "end": 0.8, "midi": 62}]
    pr, pe = real.without_technique_notes(ref, est)
    assert aggregate([clip_stats(pr, pe)])["onset"]["f1"] == 1.0
    ref2 = [
        {"start": 0.10, "end": 0.12, "midi": 60},
        {"start": 0.13, "end": 0.3, "midi": 62, "technique": "bend"},
    ]
    est2 = [{"start": 0.13, "end": 0.3, "midi": 60}]
    assert real.without_technique_notes(ref2, est2)[1] == est2


# --- integration with a real app database -----------------------------------------------


def pluck(seconds, midi, sr=48000, seed=0):
    rng = np.random.default_rng(seed)
    period = int(round(sr / (440 * 2 ** ((midi - 69) / 12))))
    buf = rng.uniform(-1, 1, period)
    out = np.empty(int(seconds * sr))
    for k in range(out.size):
        j = k % period
        out[k] = buf[j]
        buf[j] = 0.996 * 0.5 * (buf[j] + buf[(j + 1) % period])
    return (0.5 * out).astype(np.float32)


def webm(samples, sr=48000):
    buf = io.BytesIO()
    with av.open(buf, "w", format="webm") as out:
        stream = out.add_stream("libopus", rate=sr, layout="mono")
        for i in range(0, samples.size, 960):
            chunk = samples[i : i + 960]
            frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="flt", layout="mono")
            frame.sample_rate, frame.pts = sr, i
            for p in stream.encode(frame):
                out.mux(p)
        for p in stream.encode(None):
            out.mux(p)
    return buf.getvalue()


@pytest.fixture
def app(tmp_path):
    from jamrecall.app import create_app
    from jamrecall.config import Settings

    settings = Settings(
        data_dir=tmp_path / "var", transcription_engine="fixture", allow_test_adapters=True
    )
    return TestClient(create_app(settings)), tmp_path / "var"


def recorded(c, midi, seed=0):
    r = c.post(
        "/api/sessions",
        files={"audio": ("r", webm(pluck(2.0, midi, seed=seed)), "audio/webm")},
        data={"client_mime": "audio/webm", "capture_info": json.dumps({"x": 1})},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def finalize(c, sid, split, midi=60, seed="blank"):
    body = {
        "notes": [{"start_seconds": 0.0, "end_seconds": 1.0, "midi_pitch": midi}],
        "seed": seed,
        "split": split,
        "condition": "A",
        "annotator": "t",
    }
    assert c.put(f"/api/sessions/{sid}/annotation", json=body).status_code == 200
    assert c.post(f"/api/sessions/{sid}/annotation/finalize").status_code == 200


def test_dataset_comes_from_the_database_with_app_provenance(app, tmp_path):
    c, var = app
    clean = recorded(c, 57)
    finalize(c, clean, "holdout")
    c.post(f"/api/sessions/{clean}/transcriptions")  # after finalization: stays eligible
    dirty = recorded(c, 60)
    c.post(f"/api/sessions/{dirty}/transcriptions?confirm_disqualify=true")
    finalize(c, dirty, "holdout")
    dev = recorded(c, 62)
    c.post(f"/api/sessions/{dev}/transcriptions?confirm_disqualify=true")
    finalize(c, dev, "dev")
    imported = c.post(
        "/api/sessions",
        files={"audio": ("r", webm(pluck(2.0, 64)), "audio/webm")},
        data={"client_mime": "audio/webm"},
    ).json()["id"]  # no capture metadata
    finalize(c, imported, "holdout")

    clips, problems, _ = real.load_dataset(var)
    assert problems == []
    by = {x["session_id"]: x for x in clips}
    assert real.holdout_exclusion(by[clean]) == []
    assert "before the reference annotation was finalized" in real.holdout_exclusion(by[dirty])[0]
    assert real.holdout_exclusion(by[dev]) == []
    assert "not recorded with the in-app recorder" in real.holdout_exclusion(by[imported])[0]

    # Exported reference files are not inputs: editing them changes nothing.
    exported = c.get(f"/api/sessions/{dirty}/export").content
    assert exported  # (would be edited by hand; load_dataset never reads exports)
    clips2, _, _ = real.load_dataset(var)
    assert real.fingerprint(clips2) == real.fingerprint(clips)


def test_tampering_with_audio_or_database_fails_closed(app, tmp_path):
    c, var = app
    sid = recorded(c, 57)
    finalize(c, sid, "holdout")
    # Database-level edits that would launder provenance are refused by triggers.
    db = sqlite3.connect(var / "jamrecall.sqlite3", isolation_level=None)
    for sql in (
        "UPDATE sessions SET provenance_origin = 'imported'",
        "UPDATE annotations SET split = 'dev'",
        "UPDATE annotation_notes SET midi_pitch = 61",
    ):
        with pytest.raises(sqlite3.DatabaseError):
            db.execute(sql)
    db.close()
    # Replacing the audio file on disk is detected.
    path = next((var / "media" / "sessions" / sid).glob("original.*"))
    path.write_bytes(webm(pluck(2.0, 59, seed=9)))
    clips, problems, _ = real.load_dataset(var)
    assert clips == [] and "does not match its stored sha256" in problems[0]


def test_missing_or_old_database_fails_closed(tmp_path):
    assert real.load_dataset(tmp_path)[1] == [
        f"no app database at {tmp_path / 'jamrecall.sqlite3'}"
    ]
    db = sqlite3.connect(tmp_path / "jamrecall.sqlite3")
    db.execute("CREATE TABLE sessions (id TEXT)")
    db.close()
    clips, problems, _ = real.load_dataset(tmp_path)
    assert clips == [] and "predates contamination tracking" in problems[0]


def test_run_validation_end_to_end(app):
    """Both real engines run in-process on the app's decoded audio; small set -> INCOMPLETE."""
    c, var = app
    hold = recorded(c, 57, seed=1)
    finalize(c, hold, "holdout", midi=57)
    dev = recorded(c, 64, seed=2)
    finalize(c, dev, "dev", midi=64)
    report = real.run_validation(var)
    assert report["verdict"] == "INCOMPLETE"
    assert report["eligible_holdout"] == [f"A-holdout-{hold[:8]}"]
    for engine in ("basic-pitch", "pyin"):
        assert "holdout/A" in report["results"][engine]["summary"]
    assert report["results"]["basic-pitch"]["params"] == {
        k: real.app_bp_params()[k] for k in real.BENCH_BP_KEYS
    }
    assert report["results"]["basic-pitch"]["summary"]["holdout/A"]["onset"]["f1"] == 1.0


# --- Codex review round 2 (2026-10-12) ---------------------------------------------------------


def test_fresh_database_has_complete_baseline(app):
    c, var = app
    db = sqlite3.connect(var / "jamrecall.sqlite3")
    assert db.execute("SELECT status, created_at_schema FROM provenance_baseline").fetchone() == (
        "complete",
        0,
    )


def test_upgraded_database_cannot_hold_a_validation_dataset(tmp_path):
    """Findings 2 and 7: history from before full tracking cannot be vouched for -> fail closed."""
    from jamrecall.db import MIGRATIONS, migrate

    db = tmp_path / "jamrecall.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    for v, script in enumerate(MIGRATIONS[:4], start=1):
        conn.executescript(f"BEGIN; {script}; INSERT INTO schema_version VALUES ({v}); COMMIT;")
    # a schema-4 session that was later deleted: only its provenance events survive
    conn.execute(
        "INSERT INTO provenance_events (session_id, audio_sha256, kind, at) "
        "VALUES ('gone', 'sha-gone', 'created', 't')"
    )
    conn.commit()
    conn.close()
    migrate(db)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT status FROM provenance_baseline").fetchone() == ("partial",)
    assert conn.execute("SELECT 1 FROM seen_audio WHERE hash = 'sha-gone'").fetchone() == (1,)
    conn.close()
    clips, problems, _ = real.load_dataset(tmp_path)
    assert clips == [] and "existed before full contamination tracking" in problems[0]


def test_changes_during_validation_are_detected(app, monkeypatch):
    """Finding 8: contaminate and rewrite a reference while validation is running."""
    c, var = app
    hold = recorded(c, 57, seed=3)
    finalize(c, hold, "holdout", midi=57)
    original = real.analyse_all
    calls = {"n": 0}

    def tamper_midway(method, clips):
        calls["n"] += 1
        if calls["n"] == 1:  # after the dataset snapshot was read
            c.post(f"/api/sessions/{hold}/transcriptions")
            c.post(f"/api/sessions/{hold}/annotation/reopen?confirm_disqualify=true")
            body = {
                "notes": [{"start_seconds": 0.0, "end_seconds": 1.0, "midi_pitch": 61}],
                "split": "holdout",
                "condition": "A",
                "annotator": "t",
            }
            c.put(f"/api/sessions/{hold}/annotation", json=body)
            c.post(f"/api/sessions/{hold}/annotation/finalize")
        return original(method, clips)

    monkeypatch.setattr(real, "analyse_all", tamper_midway)
    report = real.run_validation(var)
    assert report["verdict"] == "INCOMPLETE"
    assert any("changed during validation" in p for p in report["integrity_problems"])
    # What was scored is the consistent pre-change snapshot (clean provenance, original notes).
    [rec] = report["recordings"]
    assert rec["notes"][0]["midi"] == 57 and rec["provenance"]["contaminated_at"] is None
