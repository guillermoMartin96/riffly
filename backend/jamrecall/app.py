"""FastAPI application: sessions (recordings), transcriptions, riffs."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from jamrecall import store
from jamrecall.audio import AudioDecodeError, decode_mono, peaks
from jamrecall.config import ACCEPTED_MIME_TYPES, Settings
from jamrecall.db import migrate, transaction
from jamrecall.service import run_transcription
from jamrecall.transcription.registry import build_adapter

EXTENSIONS = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(status, {"code": code, "message": message})


class RiffIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    start_seconds: float
    end_seconds: float

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v


def _base_mime(mime: str) -> str:
    return mime.split(";", 1)[0].strip().lower()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    migrate(settings.db_path)
    # Fail fast on a misconfigured engine (e.g. test adapter without the test flag).
    adapter = build_adapter(settings)

    app = FastAPI(title="JamRecall API", version="0.1.0")
    app.state.settings = settings

    @app.exception_handler(HTTPException)
    async def _http_error(_req: Any, exc: HTTPException) -> JSONResponse:
        detail = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {"code": "error", "message": str(exc.detail)}
        )
        return JSONResponse(detail, status_code=exc.status_code)

    def audio_file(session: dict[str, Any]) -> Path:
        return settings.data_dir / session["audio_path"]

    def session_out(session: dict[str, Any]) -> dict[str, Any]:
        out = {
            k: session[k]
            for k in (
                "id",
                "audio_mime",
                "audio_bytes",
                "audio_sha256",
                "duration_seconds",
                "sample_rate",
                "created_at",
            )
        }
        out["status"] = "ready" if audio_file(session).is_file() else "audio_missing"
        if "riff_count" in session:
            out["riff_count"] = session["riff_count"]
        return out

    def require_session(conn: Any, session_id: str) -> dict[str, Any]:
        s = store.get_session(conn, session_id)
        if s is None:
            raise ApiError(404, "session_not_found", "No session with that id")
        return s

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        with transaction(settings.db_path) as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "transcription": None
            if adapter is None
            else {
                "engine": adapter.engine,
                "version": adapter.version,
                "test_only": adapter.test_only,
            },
            "accepted_mime_types": list(ACCEPTED_MIME_TYPES),
            "max_upload_bytes": settings.max_upload_bytes,
            "max_duration_seconds": settings.max_duration_seconds,
        }

    # --- sessions -------------------------------------------------------------------------------

    @app.post("/api/sessions", status_code=201)
    async def create_session(
        audio: Annotated[UploadFile, File()],
        client_mime: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        mime = _base_mime(client_mime or audio.content_type or "")
        if mime not in ACCEPTED_MIME_TYPES:
            raise ApiError(415, "unsupported_mime", f"Unsupported audio type '{mime or 'unknown'}'")
        data = await audio.read(settings.max_upload_bytes + 1)
        if len(data) == 0:
            raise ApiError(400, "empty_recording", "The recording is empty")
        if len(data) > settings.max_upload_bytes:
            raise ApiError(413, "too_large", "Recording exceeds the upload size limit")

        sid = store.new_id()
        rel = Path("media") / "sessions" / sid / f"original.{EXTENSIONS[mime]}"
        dest = settings.data_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        try:
            buf = decode_mono(dest)
        except AudioDecodeError as exc:
            _discard(dest)
            raise ApiError(422, "undecodable_audio", str(exc)) from exc
        duration = buf.duration_seconds
        if duration > settings.max_duration_seconds:
            _discard(dest)
            raise ApiError(413, "too_long", "Recording exceeds the maximum duration")
        with transaction(settings.db_path) as conn:
            s = store.insert_session(
                conn,
                id=sid,
                audio_path=rel.as_posix(),
                audio_mime=mime,
                audio_bytes=len(data),
                audio_sha256=hashlib.sha256(data).hexdigest(),
                duration_seconds=round(duration, 6),
                sample_rate=buf.sample_rate,
                created_at=store.now_iso(),
            )
        return session_out(s)

    @app.get("/api/sessions")
    def list_sessions() -> list[dict[str, Any]]:
        with transaction(settings.db_path) as conn:
            return [session_out(s) for s in store.list_sessions(conn)]

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        with transaction(settings.db_path) as conn:
            return session_out(require_session(conn, session_id))

    @app.get("/api/sessions/{session_id}/audio")
    def get_audio(session_id: str) -> Response:
        with transaction(settings.db_path) as conn:
            s = require_session(conn, session_id)
        path = audio_file(s)
        if not path.is_file():
            raise ApiError(404, "audio_missing", "The original recording file is missing")
        return FileResponse(path, media_type=s["audio_mime"])

    @app.get("/api/sessions/{session_id}/peaks")
    def get_peaks(session_id: str, n: int = 800) -> dict[str, Any]:
        with transaction(settings.db_path) as conn:
            s = require_session(conn, session_id)
        path = audio_file(s)
        if not path.is_file():
            raise ApiError(404, "audio_missing", "The original recording file is missing")
        buf = decode_mono(path, 8000)
        return {"duration_seconds": s["duration_seconds"], "peaks": peaks(buf, n)}

    # --- transcriptions -------------------------------------------------------------------------

    def transcription_out(conn: Any, t: dict[str, Any]) -> dict[str, Any]:
        notes = store.list_notes(conn, t["id"]) if t["status"] == "succeeded" else []
        return {
            "id": t["id"],
            "session_id": t["session_id"],
            "engine": t["engine"],
            "engine_version": t["engine_version"],
            "test_only": bool(t["test_only"]),
            "status": t["status"],
            "error": t["error"],
            "created_at": t["created_at"],
            "completed_at": t["completed_at"],
            "processing_seconds": t["processing_seconds"],
            "fingering_method": t["fingering_method"],
            "notes": [
                {
                    "start_seconds": n["start_seconds"],
                    "end_seconds": n["end_seconds"],
                    "midi_pitch": n["midi_pitch"],
                    "confidence": n["confidence"],
                    "fingering": None
                    if n["string"] is None
                    else {
                        "string": n["string"],
                        "fret": n["fret"],
                        "inferred": True,
                        "alternatives": n["fingering_alternatives"],
                    },
                }
                for n in notes
            ],
        }

    @app.post("/api/sessions/{session_id}/transcriptions", status_code=202)
    def start_transcription(session_id: str, tasks: BackgroundTasks) -> dict[str, Any]:
        if adapter is None:
            raise ApiError(409, "no_engine", "No transcription engine is configured")
        with transaction(settings.db_path) as conn:
            s = require_session(conn, session_id)
            if not audio_file(s).is_file():
                raise ApiError(409, "audio_missing", "The original recording file is missing")
            t = store.insert_transcription(
                conn, session_id, adapter.engine, adapter.version, adapter.test_only
            )
            out = transcription_out(conn, t)
        tasks.add_task(run_transcription, settings, adapter, t["id"])
        return out

    @app.get("/api/sessions/{session_id}/transcriptions/latest")
    def latest_transcription(session_id: str) -> dict[str, Any]:
        with transaction(settings.db_path) as conn:
            require_session(conn, session_id)
            t = store.latest_transcription(conn, session_id)
            if t is None:
                raise ApiError(404, "no_transcription", "This session has not been transcribed")
            return transcription_out(conn, t)

    # --- riffs ----------------------------------------------------------------------------------

    @app.post("/api/sessions/{session_id}/riffs", status_code=201)
    def create_riff(session_id: str, body: RiffIn) -> dict[str, Any]:
        start, end = body.start_seconds, body.end_seconds
        with transaction(settings.db_path) as conn:
            s = require_session(conn, session_id)
            if not (math.isfinite(start) and math.isfinite(end)):
                raise ApiError(422, "invalid_range", "Start and end must be finite numbers")
            if start < 0:
                raise ApiError(422, "invalid_range", "Start must be >= 0")
            if end <= start:
                raise ApiError(422, "invalid_range", "End must be after start")
            if end > s["duration_seconds"] + 1e-6:
                raise ApiError(422, "invalid_range", "End is beyond the end of the recording")
            return store.insert_riff(
                conn,
                session_id,
                body.title,
                round(start, 6),
                round(min(end, s["duration_seconds"]), 6),
            )

    @app.get("/api/sessions/{session_id}/riffs")
    def session_riffs(session_id: str) -> list[dict[str, Any]]:
        with transaction(settings.db_path) as conn:
            require_session(conn, session_id)
            return store.list_riffs(conn, session_id)

    @app.get("/api/riffs")
    def all_riffs() -> list[dict[str, Any]]:
        with transaction(settings.db_path) as conn:
            return store.list_riffs(conn)

    @app.get("/api/riffs/{riff_id}")
    def get_riff(riff_id: str) -> dict[str, Any]:
        with transaction(settings.db_path) as conn:
            r = store.get_riff(conn, riff_id)
        if r is None:
            raise ApiError(404, "riff_not_found", "No riff with that id")
        return r

    @app.delete("/api/riffs/{riff_id}", status_code=204)
    def delete_riff(riff_id: str) -> Response:
        # Deletes only the riff row; the parent session and its source audio are untouched.
        with transaction(settings.db_path) as conn:
            if not store.delete_riff(conn, riff_id):
                raise ApiError(404, "riff_not_found", "No riff with that id")
        return Response(status_code=204)

    return app


def _discard(path: Path) -> None:
    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        pass


def get_app() -> FastAPI:
    """Factory for `uvicorn --factory jamrecall.app:get_app` (settings read from environment)."""
    return create_app()
