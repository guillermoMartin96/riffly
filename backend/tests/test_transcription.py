import math

import pytest
from conftest import tone, upload, wav_bytes

from jamrecall.config import Settings
from jamrecall.transcription.base import DetectedNote, normalize_notes
from jamrecall.transcription.registry import EngineConfigError, build_adapter


def test_no_engine_configured_returns_409(client):
    sid = upload(client, wav_bytes(tone(1.0))).json()["id"]
    r = client.post(f"/api/sessions/{sid}/transcriptions")
    assert r.status_code == 409
    assert r.json()["code"] == "no_engine"
    assert client.get(f"/api/sessions/{sid}/transcriptions/latest").status_code == 404


def test_test_adapter_refused_without_flag(tmp_path):
    with pytest.raises(EngineConfigError):
        build_adapter(Settings(data_dir=tmp_path, transcription_engine="fixture"))


def test_unknown_engine_refused(tmp_path):
    with pytest.raises(EngineConfigError):
        build_adapter(Settings(data_dir=tmp_path, transcription_engine="magic"))


def test_fixture_transcription_is_flagged_test_only(fixture_client):
    cfg = fixture_client.get("/api/config").json()
    assert cfg["transcription"] == {
        "engine": "test-fixture",
        "version": "1",
        "test_only": True,
        "validated": False,
        "model_load_seconds": 0.0,
    }
    sid = upload(fixture_client, wav_bytes(tone(3.0))).json()["id"]
    started = fixture_client.post(f"/api/sessions/{sid}/transcriptions")
    assert started.status_code == 202
    # TestClient runs background tasks before returning.
    t = fixture_client.get(f"/api/sessions/{sid}/transcriptions/latest").json()
    assert t["status"] == "succeeded"
    assert t["test_only"] is True
    assert t["engine"] == "test-fixture"
    assert t["fingering_method"] == "dp-hand-window-v1"
    assert len(t["notes"]) == 5
    for n in t["notes"]:
        assert 0 <= n["start_seconds"] < n["end_seconds"] <= 3.0
        assert n["fingering"]["inferred"] is True


def test_engine_failure_is_persisted(make_client):
    c = make_client(transcription_engine="failing", allow_test_adapters=True)
    sid = upload(c, wav_bytes(tone(1.0))).json()["id"]
    c.post(f"/api/sessions/{sid}/transcriptions")
    t = c.get(f"/api/sessions/{sid}/transcriptions/latest").json()
    assert t["status"] == "failed"
    assert "always fails" in t["error"]
    assert t["notes"] == []
    assert t["completed_at"] is not None


def test_transcribe_with_missing_audio_is_rejected(fixture_client, tmp_path):
    sid = upload(fixture_client, wav_bytes(tone(1.0))).json()["id"]
    for f in (tmp_path / "data" / "media" / "sessions" / sid).iterdir():
        f.unlink()
    r = fixture_client.post(f"/api/sessions/{sid}/transcriptions")
    assert r.status_code == 409
    assert r.json()["code"] == "audio_missing"


def test_normalize_clips_drops_and_sorts():
    raw = [
        DetectedNote(1.0, 1.5, 60.4, 1.7),
        DetectedNote(-0.2, 0.3, 50, None),
        DetectedNote(0.5, 0.5, 52, 0.5),  # zero length
        DetectedNote(1.8, 2.5, 64, 0.2),  # crosses duration
        DetectedNote(0.1, 0.2, 200, 0.5),  # invalid pitch
        DetectedNote(math.nan, 1.0, 60, 0.5),
        DetectedNote(3.0, 3.5, 60, 0.5),  # entirely after end
    ]
    out = normalize_notes(raw, duration_seconds=2.0)
    assert out == [
        DetectedNote(0.0, 0.3, 50, None),
        DetectedNote(1.0, 1.5, 60, 1.0),
        DetectedNote(1.8, 2.0, 64, 0.2),
    ]
