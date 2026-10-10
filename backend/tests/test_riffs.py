import pytest
from conftest import tone, upload, wav_bytes


@pytest.fixture
def session(client):
    return upload(client, wav_bytes(tone(4.0))).json()


def create(client, sid, title="Lick", start=0.5, end=1.75):
    return client.post(
        f"/api/sessions/{sid}/riffs",
        json={"title": title, "start_seconds": start, "end_seconds": end},
    )


def test_create_list_get_riff(client, session):
    r = create(client, session["id"], "  Opening lick ")
    assert r.status_code == 201, r.text
    riff = r.json()
    assert riff["title"] == "Opening lick"
    assert (riff["start_seconds"], riff["end_seconds"]) == (0.5, 1.75)
    assert riff["session_id"] == session["id"]
    assert client.get(f"/api/riffs/{riff['id']}").json() == riff
    assert client.get(f"/api/sessions/{session['id']}/riffs").json() == [riff]
    assert client.get("/api/riffs").json() == [riff]


def test_riff_may_end_exactly_at_duration(client, session):
    r = create(client, session["id"], start=3.0, end=session["duration_seconds"])
    assert r.status_code == 201


@pytest.mark.parametrize(
    "start,end,code",
    [
        (-0.1, 1.0, "invalid_range"),
        (2.0, 1.0, "invalid_range"),
        (1.0, 1.0, "invalid_range"),
        (1.0, 4.5, "invalid_range"),
    ],
)
def test_invalid_ranges_rejected(client, session, start, end, code):
    r = create(client, session["id"], start=start, end=end)
    assert r.status_code == 422
    assert r.json()["code"] == code


def test_non_finite_range_rejected(client, session):
    r = client.post(
        f"/api/sessions/{session['id']}/riffs",
        content=b'{"title":"x","start_seconds":NaN,"end_seconds":1}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422


@pytest.mark.parametrize("title", ["", "   ", "x" * 121])
def test_invalid_titles_rejected(client, session, title):
    assert create(client, session["id"], title=title).status_code == 422


def test_riff_for_unknown_session(client):
    r = create(client, "missing")
    assert r.status_code == 404
    assert r.json()["code"] == "session_not_found"


def test_delete_riff_keeps_session_audio_and_sibling_riffs(client, session):
    a = create(client, session["id"], "A").json()
    b = create(client, session["id"], "B", 2.0, 3.0).json()
    assert client.delete(f"/api/riffs/{a['id']}").status_code == 204
    assert client.get(f"/api/riffs/{a['id']}").status_code == 404
    assert [r["id"] for r in client.get(f"/api/sessions/{session['id']}/riffs").json()] == [b["id"]]
    assert client.get(f"/api/sessions/{session['id']}/audio").status_code == 200
    assert client.delete(f"/api/riffs/{a['id']}").status_code == 404


def test_riff_timestamps_persist_exactly_across_restart(make_client):
    c = make_client()
    sid = upload(c, wav_bytes(tone(4.0))).json()["id"]
    riff = create(c, sid, "Exact", 0.123456, 2.345678).json()
    reloaded = make_client().get(f"/api/riffs/{riff['id']}").json()
    assert (reloaded["start_seconds"], reloaded["end_seconds"]) == (0.123456, 2.345678)
