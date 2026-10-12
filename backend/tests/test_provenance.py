"""Holdout contamination guard (DR-0004 guard, approved 2026-10-12)."""

import io
import json
import sqlite3
import zipfile

import pytest
from conftest import tone, upload, wav_bytes

from jamrecall import manage
from jamrecall.db import MIGRATIONS, migrate

NOTE = [{"start_seconds": 0.25, "end_seconds": 0.65, "midi_pitch": 48, "technique": None}]


def new_session(c, freq=220.0):
    return upload(c, wav_bytes(tone(2.0, freq))).json()


def prov(c, sid):
    return c.get(f"/api/sessions/{sid}").json()["provenance"]


def finalize_holdout(c, sid, split="holdout"):
    r = c.put(
        f"/api/sessions/{sid}/annotation",
        json={"notes": NOTE, "seed": "blank", "split": split, "condition": "A", "annotator": "t"},
    )
    assert r.status_code == 200, r.text
    assert c.post(f"/api/sessions/{sid}/annotation/finalize").status_code == 200


def transcribe(c, sid, confirm=False):
    q = "?confirm_disqualify=true" if confirm else ""
    return c.post(f"/api/sessions/{sid}/transcriptions{q}")


def test_new_recording_is_tracked_and_eligible(fixture_client):
    p = new_session(fixture_client)["provenance"]
    assert p["holdout_eligible"] is True and p["tracked_since"] and p["contaminated_at"] is None


def test_transcription_before_finalization_requires_confirmation(fixture_client):
    c = fixture_client
    sid = new_session(c)["id"]
    r = transcribe(c, sid)
    assert r.status_code == 409 and r.json()["code"] == "would_disqualify_holdout"
    # Refused request leaves no trace of model output and keeps eligibility.
    assert c.get(f"/api/sessions/{sid}/transcriptions").json() == []
    assert prov(c, sid)["holdout_eligible"] is True and prov(c, sid)["model_exposed_at"] is None
    assert transcribe(c, sid, confirm=True).status_code == 202
    p = prov(c, sid)
    assert p["holdout_eligible"] is False and p["model_exposed_at"]
    assert "before the reference annotation was finalized" in p["contamination_reason"]


def test_draft_holdout_annotation_does_not_protect(fixture_client):
    c = fixture_client
    sid = new_session(c)["id"]
    c.put(
        f"/api/sessions/{sid}/annotation",
        json={"notes": NOTE, "seed": "blank", "split": "holdout", "condition": "A"},
    )
    assert transcribe(c, sid).status_code == 409  # draft is not finalized
    transcribe(c, sid, confirm=True)
    assert prov(c, sid)["holdout_eligible"] is False


def test_clean_finalization_then_transcription_stays_eligible(fixture_client):
    c = fixture_client
    sid = new_session(c)["id"]
    finalize_holdout(c, sid)
    assert transcribe(c, sid).status_code == 202  # no confirmation needed after finalization
    c.get(f"/api/sessions/{sid}/transcriptions/latest")  # viewing after finalization is fine
    p = prov(c, sid)
    assert p["holdout_eligible"] is True and p["model_exposed_at"] and p["contaminated_at"] is None


def test_reopen_after_exposure_contaminates_and_needs_confirmation(fixture_client):
    c = fixture_client
    sid = new_session(c)["id"]
    finalize_holdout(c, sid)
    transcribe(c, sid)
    r = c.post(f"/api/sessions/{sid}/annotation/reopen")
    assert r.status_code == 409 and r.json()["code"] == "would_disqualify_holdout"
    assert c.get(f"/api/sessions/{sid}/annotation").json()["status"] == "final"
    assert (
        c.post(f"/api/sessions/{sid}/annotation/reopen?confirm_disqualify=true").status_code == 200
    )
    assert prov(c, sid)["holdout_eligible"] is False
    # Refinalizing does not restore eligibility.
    assert c.post(f"/api/sessions/{sid}/annotation/finalize").status_code == 200
    assert prov(c, sid)["holdout_eligible"] is False


def test_reopen_without_exposure_is_harmless(fixture_client):
    c = fixture_client
    sid = new_session(c)["id"]
    finalize_holdout(c, sid)
    assert c.post(f"/api/sessions/{sid}/annotation/reopen").status_code == 200
    assert prov(c, sid)["holdout_eligible"] is True


def test_contamination_persists_across_restart_and_split_changes(make_client):
    c = make_client(transcription_engine="fixture", allow_test_adapters=True)
    sid = new_session(c)["id"]
    transcribe(c, sid, confirm=True)
    c.put(
        f"/api/sessions/{sid}/annotation",
        json={"notes": NOTE, "seed": "blank", "split": "dev", "condition": "A"},
    )
    c.put(
        f"/api/sessions/{sid}/annotation",
        json={"notes": NOTE, "seed": "blank", "split": "holdout", "condition": "A"},
    )
    restarted = make_client(transcription_engine="fixture", allow_test_adapters=True)
    assert prov(restarted, sid)["holdout_eligible"] is False


def test_deleting_transcriptions_or_sql_resets_cannot_clear(fixture_client, tmp_path):
    c = fixture_client
    sid = new_session(c)["id"]
    transcribe(c, sid, confirm=True)
    db = sqlite3.connect(tmp_path / "data" / "jamrecall.sqlite3")
    db.execute("DELETE FROM note_events")
    db.execute("DELETE FROM transcriptions")
    db.commit()
    assert prov(c, sid)["holdout_eligible"] is False
    for sql in (
        "UPDATE sessions SET contaminated_at = NULL",
        "UPDATE sessions SET contamination_reason = 'fine'",
        "UPDATE sessions SET model_exposed_at = NULL",
        "UPDATE sessions SET provenance_tracked_since = 'x'",
        "DELETE FROM provenance_events",
        "UPDATE provenance_events SET kind = 'x'",
        "DELETE FROM contaminated_audio",
    ):
        with pytest.raises(sqlite3.DatabaseError):
            db.execute(sql)
    assert prov(c, sid)["holdout_eligible"] is False


def test_reuploading_contaminated_audio_inherits_contamination(fixture_client):
    c = fixture_client
    data = wav_bytes(tone(2.0, 330))
    sid = upload(c, data).json()["id"]
    transcribe(c, sid, confirm=True)
    assert c.delete(f"/api/sessions/{sid}").status_code == 204
    again = upload(c, data).json()
    assert again["provenance"]["holdout_eligible"] is False
    assert "identical to a previously contaminated" in again["provenance"]["contamination_reason"]
    other = upload(c, wav_bytes(tone(2.0, 331))).json()
    assert other["provenance"]["holdout_eligible"] is True


def test_export_carries_provenance_and_events(fixture_client):
    c = fixture_client
    sid = new_session(c)["id"]
    finalize_holdout(c, sid)
    transcribe(c, sid)
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/sessions/{sid}/export").content))
    meta = json.loads(z.read("metadata.json"))
    assert meta["provenance"]["holdout_eligible"] is True
    kinds = [e["kind"] for e in meta["provenance_events"]]
    assert kinds[:3] == ["created", "annotation_finalized", "transcription_requested"]
    ref = json.loads(z.read("reference.json"))
    assert ref["provenance"]["holdout_eligible"] is True
    # The export itself was logged as an exposure.
    sid2 = new_session(c, 440)["id"]
    transcribe(c, sid2, confirm=True)
    c.get(f"/api/sessions/{sid2}/export")
    z2 = zipfile.ZipFile(io.BytesIO(c.get(f"/api/sessions/{sid2}/export").content))
    meta2 = json.loads(z2.read("metadata.json"))
    assert meta2["provenance"]["holdout_eligible"] is False
    assert any(
        e["kind"] == "model_output_exposed" and e["detail"]["via"] == "export"
        for e in meta2["provenance_events"]
    )


def test_cli_export_references_reports_db_provenance(fixture_client, tmp_path, monkeypatch):
    monkeypatch.setenv("JAMRECALL_DATA_DIR", str(tmp_path / "data"))
    c = fixture_client
    sid = new_session(c)["id"]
    transcribe(c, sid, confirm=True)
    finalize_holdout(c, sid)
    assert manage.main(["export-references", "--out", str(tmp_path / "refs")]) == 0
    [f] = list((tmp_path / "refs").glob("*.json"))
    assert json.loads(f.read_text())["provenance"]["holdout_eligible"] is False


def test_migration_marks_previously_transcribed_recordings_uncertain(tmp_path):
    db = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    for v, script in enumerate(MIGRATIONS[:3], start=1):
        conn.executescript(f"BEGIN; {script}; INSERT INTO schema_version VALUES ({v}); COMMIT;")
    for sid in ("clean", "used"):
        conn.execute(
            "INSERT INTO sessions (id, audio_path, audio_mime, audio_bytes, audio_sha256, "
            "duration_seconds, sample_rate, created_at) VALUES (?, 'p', 'audio/wav', 1, ?, 1, "
            "22050, 't')",
            (sid, f"sha-{sid}"),
        )
    conn.execute(
        "INSERT INTO transcriptions (id, session_id, engine, engine_version, status, "
        "created_at) VALUES ('t1', 'used', 'e', '1', 'succeeded', 't')"
    )
    conn.commit()
    conn.close()
    assert migrate(db) == len(MIGRATIONS)
    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT id, contamination_reason FROM sessions").fetchall())
    assert rows["clean"] is None
    assert rows["used"].startswith("uncertain")
    assert conn.execute("SELECT COUNT(*) FROM contaminated_audio").fetchone() == (1,)
    assert conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE provenance_tracked_since IS NULL"
    ).fetchone() == (0,)
