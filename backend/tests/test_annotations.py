import io
import json
import sqlite3
import zipfile

import pytest
from conftest import tone, upload, wav_bytes

from jamrecall import manage
from jamrecall.db import MIGRATIONS, migrate


@pytest.fixture
def sid(fixture_client):
    s = fixture_client.post(
        "/api/sessions",
        files={"audio": ("rec", wav_bytes(tone(4.0)), "audio/wav")},
        data={
            "client_mime": "audio/wav",
            "capture_info": json.dumps({"sampleRate": 48000, "echoCancellation": False}),
        },
    ).json()
    return s["id"]


def put(c, sid, notes, **kw):
    body = {"notes": notes, **kw}
    return c.put(f"/api/sessions/{sid}/annotation", json=body)


def n(start, end, midi, technique=None):
    return {"start_seconds": start, "end_seconds": end, "midi_pitch": midi, "technique": technique}


def test_capture_info_stored_and_validated(fixture_client, sid):
    assert fixture_client.get(f"/api/sessions/{sid}").json()["capture_info"] == {
        "sampleRate": 48000,
        "echoCancellation": False,
    }
    r = fixture_client.post(
        "/api/sessions",
        files={"audio": ("rec", wav_bytes(tone(1.0)), "audio/wav")},
        data={"client_mime": "audio/wav", "capture_info": "[1,2]"},
    )
    assert r.status_code == 422


def test_annotation_is_separate_from_model_output(fixture_client, sid):
    c = fixture_client
    c.post(f"/api/sessions/{sid}/transcriptions")
    model = c.get(f"/api/sessions/{sid}/transcriptions/latest").json()
    seed = [n(x["start_seconds"], x["end_seconds"], x["midi_pitch"]) for x in model["notes"]]
    # correct: delete a false positive, fix a pitch, adjust timing, add a missed note
    edited = seed[1:]
    edited[0] = n(edited[0]["start_seconds"] + 0.01, edited[0]["end_seconds"], 64, "bend")
    edited.append(n(3.7, 3.95, 67))  # after the last fixture note (3.25-3.65)
    r = put(
        c,
        sid,
        edited,
        seed=f"transcription:{model['id']}",
        split="dev",
        condition="A",
        annotator="tech lead",
    )
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["status"] == "draft" and a["revision"] == 1
    assert a["seed"].startswith(f"transcription:{model['id']}:test-fixture@")
    assert len(a["notes"]) == len(seed)
    assert a["notes"][0]["midi_pitch"] == 64 and a["notes"][0]["technique"] == "bend"
    # model output untouched
    again = c.get(f"/api/sessions/{sid}/transcriptions/latest").json()
    assert again["notes"] == model["notes"]


def test_annotation_validation(fixture_client, sid):
    c = fixture_client
    assert put(c, sid, [n(0.5, 0.4, 60)]).json()["code"] == "invalid_note"
    assert put(c, sid, [n(3.9, 4.5, 60)]).json()["code"] == "invalid_note"  # beyond duration
    assert put(c, sid, [n(0.1, 0.2, 200)]).status_code == 422
    assert put(c, sid, [n(0.1, 0.2, 60, "tapping")]).json()["code"] == "invalid_note"
    assert put(c, sid, [n(0.1, 0.5, 60), n(0.4, 0.6, 62)]).json()["code"] == "notes_overlap"
    assert (
        put(c, sid, [n(0.1, 0.2, 60)], seed="transcription:nope").json()["code"] == "invalid_seed"
    )
    assert put(c, sid, [n(0.1, 0.2, 60)], split="train").status_code == 422
    # unsorted input is accepted and sorted
    r = put(c, sid, [n(1.0, 1.2, 62), n(0.1, 0.2, 60)])
    assert [x["midi_pitch"] for x in r.json()["notes"]] == [60, 62]
    assert r.json()["seed"] == "blank"


def test_finalize_locks_split_and_edits(fixture_client, sid):
    c = fixture_client
    put(c, sid, [n(0.1, 0.2, 60)], split="holdout")
    r = c.post(f"/api/sessions/{sid}/annotation/finalize")
    assert r.status_code == 422 and "condition" in r.json()["message"]
    put(c, sid, [n(0.1, 0.2, 60)], split="holdout", condition="B", annotator="me")
    r = c.post(f"/api/sessions/{sid}/annotation/finalize")
    assert r.status_code == 200 and r.json()["status"] == "final" and r.json()["split_locked"]
    assert put(c, sid, [n(0.1, 0.3, 60)], split="holdout").json()["code"] == "annotation_final"
    r = c.post(f"/api/sessions/{sid}/annotation/reopen").json()
    assert r["status"] == "draft" and r["revision"] == 2
    moved = put(c, sid, [n(0.1, 0.2, 60)], split="dev", condition="B", annotator="me")
    assert moved.status_code == 409 and moved.json()["code"] == "split_locked"
    assert (
        put(c, sid, [n(0.1, 0.3, 60)], split="holdout", condition="B", annotator="me").status_code
        == 200
    )


def test_export_zip(fixture_client, sid):
    c = fixture_client
    c.post(f"/api/sessions/{sid}/transcriptions")
    put(c, sid, [n(0.25, 0.65, 48)], split="dev", condition="A", annotator="me")
    r = c.get(f"/api/sessions/{sid}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {
        "audio/original.wav",
        "metadata.json",
        "transcriptions.json",
        "reference.json",
        "README.txt",
    } <= names
    meta = json.loads(z.read("metadata.json"))
    original = c.get(f"/api/sessions/{sid}/audio").content
    assert z.read("audio/original.wav") == original
    import hashlib

    assert meta["session"]["audio_sha256"] == hashlib.sha256(original).hexdigest()
    assert meta["session"]["capture_info"]["sampleRate"] == 48000
    ref = json.loads(z.read("reference.json"))
    assert ref["format"] == "jamrecall-reference-v1" and ref["session_id"] == sid
    assert ref["notes"] == [{"start": 0.25, "end": 0.65, "midi": 48, "technique": None}]
    runs = json.loads(z.read("transcriptions.json"))
    assert runs[0]["engine"] == "test-fixture" and runs[0]["test_only"] is True


def test_delete_session_removes_everything(fixture_client, sid, tmp_path):
    c = fixture_client
    c.post(f"/api/sessions/{sid}/transcriptions")
    put(c, sid, [n(0.1, 0.2, 60)])
    c.post(f"/api/sessions/{sid}/riffs", json={"title": "x", "start_seconds": 0, "end_seconds": 1})
    media = tmp_path / "data" / "media" / "sessions" / sid
    assert media.is_dir()
    assert c.delete(f"/api/sessions/{sid}").status_code == 204
    assert not media.exists()
    assert c.get(f"/api/sessions/{sid}").status_code == 404
    assert c.get("/api/riffs").json() == []
    db = sqlite3.connect(tmp_path / "data" / "jamrecall.sqlite3")
    for table in ("annotations", "annotation_notes", "transcriptions", "note_events", "riffs"):
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert c.delete(f"/api/sessions/{sid}").status_code == 404


def test_cli_list_export_delete(fixture_client, sid, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JAMRECALL_DATA_DIR", str(tmp_path / "data"))
    put(fixture_client, sid, [n(0.1, 0.2, 60)], split="holdout", condition="C", annotator="me")
    assert manage.main(["export-references", "--out", str(tmp_path / "refs")]) == 0
    assert not list((tmp_path / "refs").glob("*.json"))  # drafts are skipped
    fixture_client.post(f"/api/sessions/{sid}/annotation/finalize")
    assert manage.main(["export-references", "--out", str(tmp_path / "refs")]) == 0
    [ref_file] = list((tmp_path / "refs").glob("*.json"))
    assert ref_file.name.startswith("C-holdout-")
    assert json.loads(ref_file.read_text())["audio_sha256"]
    assert manage.main(["list"]) == 0
    assert sid in capsys.readouterr().out
    assert manage.main(["export-session", sid, "--out", str(tmp_path / "zips")]) == 0
    assert manage.main(["delete-session", sid]) == 1  # needs --yes
    assert manage.main(["delete-session", sid, "--yes"]) == 0
    assert fixture_client.get(f"/api/sessions/{sid}").status_code == 404
    assert manage.main(["wipe"]) == 1
    assert manage.main(["wipe", "--yes"]) == 0
    assert not (tmp_path / "data").exists()


def test_migration_upgrades_existing_database(tmp_path):
    db = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    for v, script in enumerate(MIGRATIONS[:2], start=1):
        conn.executescript(f"BEGIN; {script}; INSERT INTO schema_version VALUES ({v}); COMMIT;")
    conn.execute(
        "INSERT INTO sessions (id, audio_path, audio_mime, audio_bytes, audio_sha256, "
        "duration_seconds, sample_rate, created_at) VALUES ('s', 'p', 'audio/wav', 1, 'h', 1, "
        "22050, 't')"
    )
    conn.commit()
    conn.close()
    assert migrate(db) == len(MIGRATIONS)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT capture_info FROM sessions").fetchone() == (None,)
    assert conn.execute("SELECT COUNT(*) FROM annotations").fetchone() == (0,)


def test_upload_without_capture_info_still_works(client):
    r = upload(client, wav_bytes(tone(1.0)))
    assert r.status_code == 201 and r.json()["capture_info"] is None


def test_rounding_cannot_produce_zero_length_note(fixture_client, sid):
    r = put(fixture_client, sid, [n(0.10001, 0.10002, 60)])
    assert r.status_code == 422 and r.json()["code"] == "invalid_note"
    r = fixture_client.post(
        f"/api/sessions/{sid}/riffs",
        json={"title": "x", "start_seconds": 0.1000001, "end_seconds": 0.1000002},
    )
    assert r.status_code == 422
