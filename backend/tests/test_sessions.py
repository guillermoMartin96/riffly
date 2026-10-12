import hashlib

from conftest import tone, upload, wav_bytes, webm_opus_bytes


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_config_without_engine(client):
    cfg = client.get("/api/config").json()
    assert cfg["transcription"] is None
    assert "audio/webm" in cfg["accepted_mime_types"]


def test_upload_wav_stores_original_bytes_and_measures_duration(client, tmp_path):
    data = wav_bytes(tone(2.5))
    r = upload(client, data)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["status"] == "ready"
    assert abs(s["duration_seconds"] - 2.5) < 0.001
    assert s["audio_bytes"] == len(data)
    assert s["audio_sha256"] == hashlib.sha256(data).hexdigest()
    # Byte-for-byte original is served back.
    audio = client.get(f"/api/sessions/{s['id']}/audio")
    assert audio.status_code == 200
    assert audio.content == data
    assert audio.headers["content-type"].startswith("audio/wav")


def test_upload_webm_opus_like_mediarecorder(client):
    data = webm_opus_bytes(tone(3.0))
    r = upload(client, data, "audio/webm;codecs=opus")
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["audio_mime"] == "audio/webm"
    # Opus frames are 20 ms; decoded length is within one frame of the input.
    assert abs(s["duration_seconds"] - 3.0) < 0.03


def test_audio_supports_range_requests(client):
    data = wav_bytes(tone(1.0))
    sid = upload(client, data).json()["id"]
    r = client.get(f"/api/sessions/{sid}/audio", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206
    assert r.content == data[100:200]


def test_rejects_empty_recording(client):
    r = upload(client, b"")
    assert r.status_code == 400
    assert r.json()["code"] == "empty_recording"


def test_rejects_unsupported_mime(client):
    r = upload(client, b"abc", "video/mp4")
    assert r.status_code == 415
    assert r.json()["code"] == "unsupported_mime"


def test_rejects_undecodable_audio_and_leaves_no_file(client, tmp_path):
    r = upload(client, b"not really audio at all" * 10, "audio/webm")
    assert r.status_code == 422
    assert r.json()["code"] == "undecodable_audio"
    assert client.get("/api/sessions").json() == []
    assert not any((tmp_path / "data" / "media" / "sessions").glob("*/original.*"))


def test_rejects_oversized_upload(make_client):
    c = make_client(max_upload_bytes=1000)
    r = upload(c, wav_bytes(tone(1.0)))
    assert r.status_code == 413


def test_rejects_too_long_recording(make_client):
    c = make_client(max_duration_seconds=1.0)
    r = upload(c, wav_bytes(tone(2.0)))
    assert r.status_code == 413
    assert r.json()["code"] == "too_long"


def test_missing_audio_file_is_reported(client, tmp_path):
    sid = upload(client, wav_bytes(tone(1.0))).json()["id"]
    for f in (tmp_path / "data" / "media" / "sessions" / sid).iterdir():
        f.unlink()
    assert client.get(f"/api/sessions/{sid}").json()["status"] == "audio_missing"
    r = client.get(f"/api/sessions/{sid}/audio")
    assert r.status_code == 404
    assert r.json()["code"] == "audio_missing"


def test_unknown_session_404(client):
    r = client.get("/api/sessions/nope")
    assert r.status_code == 404
    assert r.json()["code"] == "session_not_found"


def test_peaks(client):
    sid = upload(client, wav_bytes(tone(1.0))).json()["id"]
    p = client.get(f"/api/sessions/{sid}/peaks?n=50").json()
    assert len(p["peaks"]) == 50
    assert 0.35 < max(p["peaks"]) <= 0.41


def test_sessions_persist_across_app_restart(make_client):
    sid = upload(make_client(), wav_bytes(tone(1.0))).json()["id"]
    restarted = make_client()
    assert [s["id"] for s in restarted.get("/api/sessions").json()] == [sid]
