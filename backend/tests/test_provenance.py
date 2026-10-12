"""Holdout contamination guard (DR-0004 guard, approved 2026-10-12)."""

import io
import json
import sqlite3
import zipfile

import pytest
from conftest import tone, upload, wav_bytes, webm_opus_bytes

from jamrecall import manage
from jamrecall.db import MIGRATIONS, migrate

NOTE = [{"start_seconds": 0.25, "end_seconds": 0.65, "midi_pitch": 48, "technique": None}]


CAPTURE = json.dumps({"mime_type": "audio/webm;codecs=opus", "track_settings": {}})


def recorded(c, data: bytes):
    """Upload like the in-app recorder: Opus/WebM with browser capture metadata."""
    return c.post(
        "/api/sessions",
        files={"audio": ("rec", data, "audio/webm")},
        data={"client_mime": "audio/webm", "capture_info": CAPTURE},
    )


def new_session(c, freq=220.0):
    r = recorded(c, webm_opus_bytes(tone(2.0, freq)))
    assert r.status_code == 201, r.text
    return r.json()


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
    db = sqlite3.connect(tmp_path / "data" / "jamrecall.sqlite3", isolation_level=None)
    db.execute("DELETE FROM note_events")
    db.execute("DELETE FROM transcriptions")
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
    data = webm_opus_bytes(tone(2.0, 330))
    sid = recorded(c, data).json()["id"]
    transcribe(c, sid, confirm=True)
    assert c.delete(f"/api/sessions/{sid}").status_code == 204
    again = recorded(c, data).json()
    assert again["provenance"]["holdout_eligible"] is False
    assert "identical to a previously contaminated" in again["provenance"]["contamination_reason"]
    other = recorded(c, webm_opus_bytes(tone(2.0, 331))).json()
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


# --- hardening after the Codex review of the guard (2026-10-12) ----------------------------------


def test_db_invariants_reject_out_of_order_writes(fixture_client, tmp_path):
    """Even bypassing the API, the database refuses writes that would skip contamination."""
    c = fixture_client
    db = sqlite3.connect(tmp_path / "data" / "jamrecall.sqlite3", isolation_level=None)
    fresh = new_session(c, 500)["id"]
    with pytest.raises(sqlite3.DatabaseError, match="before creating a transcription"):
        db.execute(
            "INSERT INTO transcriptions (id, session_id, engine, engine_version, status, "
            "created_at) VALUES ('x', ?, 'e', '1', 'pending', 't')",
            (fresh,),
        )
    done = new_session(c, 510)["id"]
    finalize_holdout(c, done)
    transcribe(c, done)  # exposure after finalization: allowed, still eligible
    with pytest.raises(sqlite3.DatabaseError, match="before reopening"):
        db.execute("UPDATE annotations SET status = 'draft' WHERE session_id = ?", (done,))
    aid = db.execute("SELECT id FROM annotations WHERE session_id = ?", (done,)).fetchone()[0]
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        db.execute(
            "INSERT INTO annotation_notes (annotation_id, start_seconds, end_seconds, "
            "midi_pitch) VALUES (?, 1.0, 1.2, 60)",
            (aid,),
        )
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        db.execute("UPDATE annotation_notes SET midi_pitch = 61 WHERE annotation_id = ?", (aid,))
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        db.execute("UPDATE annotations SET split = 'dev' WHERE session_id = ?", (done,))
    assert prov(c, done)["holdout_eligible"] is True


def test_concurrent_reopen_and_transcribe_cannot_leave_an_exposed_draft_eligible(make_client):
    """Codex finding 1: race reopen against transcription from two app instances."""
    import threading

    a = make_client(transcription_engine="fixture", allow_test_adapters=True)
    b = make_client(transcription_engine="fixture", allow_test_adapters=True)
    sids = []
    for i in range(12):
        sid = new_session(a, 600 + i)["id"]
        finalize_holdout(a, sid)
        sids.append(sid)
    for sid in sids:
        barrier = threading.Barrier(2)

        def reopen(sid=sid, barrier=barrier):
            barrier.wait()
            a.post(f"/api/sessions/{sid}/annotation/reopen")

        def tx(sid=sid, barrier=barrier):
            barrier.wait()
            b.post(f"/api/sessions/{sid}/transcriptions")

        threads = [threading.Thread(target=reopen), threading.Thread(target=tx)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        p = prov(a, sid)
        status = a.get(f"/api/sessions/{sid}/annotation").json()["status"]
        exposed = p["model_exposed_at"] is not None
        # Invariant: an exposed recording whose reference is open again must be contaminated.
        assert not (exposed and status == "draft" and p["holdout_eligible"]), (sid, p, status)


def test_reupload_after_post_final_transcription_is_ineligible(fixture_client):
    """Codex finding 2: transcribe after finalization (clean), then re-upload identical audio."""
    c = fixture_client
    data = webm_opus_bytes(tone(2.0, 700))
    first = recorded(c, data).json()["id"]
    finalize_holdout(c, first)
    transcribe(c, first)
    assert prov(c, first)["holdout_eligible"] is True
    c.delete(f"/api/sessions/{first}")
    again = recorded(c, data).json()
    assert again["provenance"]["holdout_eligible"] is False
    assert "duplicate of audio uploaded before" in again["provenance"]["contamination_reason"]


def test_rewrapped_audio_with_same_samples_is_ineligible(fixture_client):
    """Codex finding 7: same decoded samples in different container bytes."""
    import av

    c = fixture_client
    samples = tone(2.0, 710)
    first = recorded(c, webm_opus_bytes(samples)).json()
    buf = io.BytesIO()
    with (
        av.open(io.BytesIO(webm_opus_bytes(samples))) as src,
        av.open(buf, "w", format="webm") as out,
    ):
        out.metadata["title"] = "re-wrapped"
        stream = out.add_stream_from_template(src.streams.audio[0])
        for packet in src.demux(src.streams.audio[0]):
            if packet.dts is None:
                continue
            packet.stream = stream
            out.mux(packet)
    rewrapped = buf.getvalue()
    assert rewrapped != webm_opus_bytes(samples)
    again = recorded(c, rewrapped).json()
    assert again["audio_sha256"] != first["audio_sha256"]
    assert again["provenance"]["holdout_eligible"] is False
    assert "duplicate" in again["provenance"]["contamination_reason"]


def test_imported_files_are_never_holdout_eligible(fixture_client):
    """Uploads without the in-app recorder's capture metadata, or as WAV, are imports."""
    c = fixture_client
    plain = upload(c, wav_bytes(tone(2.0, 720))).json()
    assert plain["provenance"]["holdout_eligible"] is False
    assert plain["provenance"]["ineligible_reason"] == "not recorded with the in-app recorder"
    wav_with_meta = c.post(
        "/api/sessions",
        files={"audio": ("r", wav_bytes(tone(2.0, 721)), "audio/wav")},
        data={"client_mime": "audio/wav", "capture_info": CAPTURE},
    ).json()
    assert wav_with_meta["provenance"]["origin"] == "imported"


def test_sessions_from_before_tracking_are_never_eligible(tmp_path):
    """Codex finding 5: absence of a transcription row is not evidence of clean provenance."""
    db = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    for v, script in enumerate(MIGRATIONS[:3], start=1):
        conn.executescript(f"BEGIN; {script}; INSERT INTO schema_version VALUES ({v}); COMMIT;")
    conn.execute(
        "INSERT INTO sessions (id, audio_path, audio_mime, audio_bytes, audio_sha256, "
        "duration_seconds, sample_rate, created_at, capture_info) VALUES ('old', 'p', "
        "'audio/webm', 1, 'sha-old', 1, 22050, 't', '{}')"
    )
    conn.commit()
    conn.close()
    migrate(db)
    from jamrecall import provenance

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute("SELECT * FROM sessions WHERE id = 'old'").fetchone())
    assert row["provenance_origin"] == "pre-tracking"
    st = provenance.status(row, baseline_ok=True)  # origin rule alone
    assert st["holdout_eligible"] is False and "tracked from creation" in st["ineligible_reason"]
    assert (
        "existed before full contamination tracking" in provenance.status(row)["ineligible_reason"]
    )  # and this upgraded database's baseline is 'partial' anyway
    assert conn.execute("SELECT status FROM provenance_baseline").fetchone()[0] == "partial"
    assert conn.execute("SELECT COUNT(*) FROM seen_audio WHERE hash = 'sha-old'").fetchone()[0] == 1


def test_finalize_is_idempotent_and_final_rows_cannot_be_inserted(fixture_client, tmp_path):
    """Codex round 2 finding 9, plus: references cannot be created already final."""
    c = fixture_client
    sid = new_session(c, 800)["id"]
    finalize_holdout(c, sid)
    first = c.get(f"/api/sessions/{sid}/annotation").json()["finalized_at"]
    import time

    time.sleep(0.01)
    r = c.post(f"/api/sessions/{sid}/annotation/finalize")
    assert r.status_code == 200 and r.json()["finalized_at"] == first
    db = sqlite3.connect(tmp_path / "data" / "jamrecall.sqlite3", isolation_level=None)
    other = new_session(c, 810)["id"]
    with pytest.raises(sqlite3.DatabaseError, match="created as drafts"):
        db.execute(
            "INSERT INTO annotations (id, session_id, status, method, seed, created_at, "
            "updated_at) VALUES ('x', ?, 'final', 'manual', 'blank', 't', 't')",
            (other,),
        )


def test_partial_database_reports_nothing_eligible(tmp_path):
    """Codex round 3 finding 2: in an upgraded database the app must not advertise eligibility."""
    from fastapi.testclient import TestClient

    from jamrecall.app import create_app
    from jamrecall.config import Settings

    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(data / "jamrecall.sqlite3")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    for v, script in enumerate(MIGRATIONS[:5], start=1):
        conn.executescript(f"BEGIN; {script}; INSERT INTO schema_version VALUES ({v}); COMMIT;")
    conn.close()
    c = TestClient(
        create_app(
            Settings(data_dir=data, transcription_engine="fixture", allow_test_adapters=True)
        )
    )
    p = new_session(c, 900)["provenance"]
    assert p["holdout_eligible"] is False
    assert p["ineligible_reason"] == "data directory existed before full contamination tracking"


def test_fresh_initialisation_is_atomic_and_complete(tmp_path):
    db = tmp_path / "fresh.sqlite3"
    assert migrate(db) == len(MIGRATIONS)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT status, created_at_schema FROM provenance_baseline").fetchone() == (
        "complete",
        0,
    )
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == len(MIGRATIONS)
    assert migrate(db) == len(MIGRATIONS)  # re-running changes nothing
    assert conn.execute("SELECT COUNT(*) FROM provenance_baseline").fetchone()[0] == 1


def test_finalize_twice_logs_one_event(fixture_client):
    c = fixture_client
    sid = new_session(c, 910)["id"]
    finalize_holdout(c, sid)
    c.post(f"/api/sessions/{sid}/annotation/finalize")
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/sessions/{sid}/export").content))
    kinds = [e["kind"] for e in json.loads(z.read("metadata.json"))["provenance_events"]]
    assert kinds.count("annotation_finalized") == 1


# --- Codex review round 4: exposure follows audio identity across sessions ---------------


def _remux(data: bytes) -> bytes:
    """Same decoded samples, different container bytes."""
    import av

    buf = io.BytesIO()
    with av.open(io.BytesIO(data)) as src, av.open(buf, "w", format="webm") as out:
        out.metadata["title"] = "remux"
        stream = out.add_stream_from_template(src.streams.audio[0])
        for packet in src.demux(src.streams.audio[0]):
            if packet.dts is None:
                continue
            packet.stream = stream
            out.mux(packet)
    return buf.getvalue()


def _import(c, data: bytes):
    return c.post(
        "/api/sessions",
        files={"audio": ("r", data, "audio/webm")},
        data={"client_mime": "audio/webm"},
    ).json()


def test_model_output_for_a_copy_contaminates_the_unfinalized_original(fixture_client):
    """Codex round 4: A recorded (not finalized); B = remux of A imported and transcribed."""
    c = fixture_client
    data = webm_opus_bytes(tone(2.0, 1000))
    a = recorded(c, data).json()["id"]
    b = _import(c, _remux(data))
    assert b["provenance"]["holdout_eligible"] is False  # duplicate + import
    r = transcribe(c, b["id"])
    assert r.status_code == 409 and r.json()["code"] == "would_disqualify_holdout"
    assert prov(c, a)["holdout_eligible"] is True  # refused: nothing recorded
    assert transcribe(c, b["id"], confirm=True).status_code == 202
    pa = prov(c, a)
    assert pa["holdout_eligible"] is False and pa["model_exposed_at"]
    assert f"identical audio in session {b['id']}" in pa["contamination_reason"]
    finalize_holdout(c, a)
    assert prov(c, a)["holdout_eligible"] is False


def test_model_output_for_a_copy_after_finalization_exposes_the_original(fixture_client):
    c = fixture_client
    data = webm_opus_bytes(tone(2.0, 1010))
    a = recorded(c, data).json()["id"]
    finalize_holdout(c, a)
    b = _import(c, _remux(data))
    assert transcribe(c, b["id"]).status_code == 202  # A is final, B already ineligible
    pa = prov(c, a)
    assert pa["holdout_eligible"] is True and pa["model_exposed_at"]
    r = c.post(f"/api/sessions/{a}/annotation/reopen")
    assert r.status_code == 409  # reopening A now needs confirmation and contaminates
    c.post(f"/api/sessions/{a}/annotation/reopen?confirm_disqualify=true")
    assert prov(c, a)["holdout_eligible"] is False


def test_contamination_records_decoded_audio_identity(fixture_client, tmp_path):
    c = fixture_client
    data = webm_opus_bytes(tone(2.0, 1020))
    s = recorded(c, data).json()
    transcribe(c, s["id"], confirm=True)
    db = sqlite3.connect(tmp_path / "data" / "jamrecall.sqlite3")
    pcm = db.execute("SELECT pcm_sha256 FROM sessions WHERE id = ?", (s["id"],)).fetchone()[0]
    hashes = {r[0] for r in db.execute("SELECT audio_sha256 FROM contaminated_audio")}
    assert {s["audio_sha256"], pcm} <= hashes
