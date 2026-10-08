"""FastAPI app implementing docs/api-contract.md."""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from .analysis import Analysis, TextTooShortToScore, score_text
from .auth import COOKIE_NAME, SessionSigner, password_matches, read_keychain_password
from .backend import LlamaCppPair, PairBackend
from .calibration import CalibrationStore
from .config import Settings
from .extract import ExtractError, extract_text
from .jobs import JobFailed, JobQueue, ModelManager, QueueFull
from .ratelimit import SlidingWindowLimiter
from .textproc import TextTokenizer, count_words

log = logging.getLogger("squint.app")

FROM_KEYCHAIN = object()


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.headers, self.extra = status, code, message, headers, extra


def error_response(status: int, code: str, message: str, headers: dict | None = None, **extra) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status, headers=headers)


def client_key(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    return request.client.host if request.client else "unknown"


def _is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    return '"https"' in request.headers.get("cf-visitor", "")


async def read_body_capped(request: Request, cap: int, code: str, message: str) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > cap:
        raise ApiError(413, code, message)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > cap:
            raise ApiError(413, code, message)
    return bytes(buf)


def parse_multipart_file(content_type: str, body: bytes, field: str = "file") -> tuple[str, bytes] | None:
    """In-memory multipart parsing (Starlette's parser spools big files to a temp file on disk)."""
    from python_multipart.multipart import MultipartParser, parse_options_header

    _, params = parse_options_header(content_type)
    boundary = params.get(b"boundary")
    if not boundary:
        return None
    parts: list[dict] = []
    cur: dict = {}
    hdr = {"name": b"", "value": b""}

    def on_part_begin():
        cur.clear()
        cur.update(headers={}, data=bytearray())

    def on_header_field(d, s, e):
        hdr["name"] += d[s:e]

    def on_header_value(d, s, e):
        hdr["value"] += d[s:e]

    def on_header_end():
        cur["headers"][hdr["name"].lower()] = hdr["value"]
        hdr["name"] = hdr["value"] = b""

    def on_part_data(d, s, e):
        cur["data"] += d[s:e]

    def on_part_end():
        parts.append({"headers": dict(cur["headers"]), "data": cur["data"]})

    parser = MultipartParser(boundary, {
        "on_part_begin": on_part_begin, "on_header_field": on_header_field,
        "on_header_value": on_header_value, "on_header_end": on_header_end,
        "on_part_data": on_part_data, "on_part_end": on_part_end,
    })
    parser.write(body)
    parser.finalize()
    for p in parts:
        _, opts = parse_options_header(p["headers"].get(b"content-disposition", b""))
        if opts.get(b"name") == field.encode() and b"filename" in opts:
            return opts[b"filename"].decode("utf-8", "replace"), bytes(p["data"])
    return None


class Services:
    """Everything the routes share; one instance per app."""

    def __init__(self, settings: Settings, backend_factory: Callable[[], PairBackend] | None,
                 tokenizer: TextTokenizer | None, password, job_tick_s: float = 1.0):
        self.settings = settings
        self.profile = settings.profile
        self.calibration = CalibrationStore(settings.calibration_dir)
        self._tokenizer = tokenizer
        self._tok_lock = threading.Lock()
        if password is FROM_KEYCHAIN:
            password = read_keychain_password(settings.keychain_service)
        self.password: str | None = password
        self.signer = SessionSigner(settings.session_ttl_s)
        self.analyze_limiter = SlidingWindowLimiter(settings.limits.checks_per_hour, 3600)
        self.login_limiter = SlidingWindowLimiter(settings.login_max_failures, settings.login_window_s)
        self.login_global = SlidingWindowLimiter(settings.login_global_max_failures, settings.login_global_window_s)
        factory = backend_factory or (lambda: LlamaCppPair(self.profile))
        self.manager = ModelManager(factory, settings.idle_unload_s)
        self.queue = JobQueue(self.process, self.manager, result_ttl_s=settings.result_ttl_s,
                              max_queue=settings.max_queue, tick_s=job_tick_s)

    @property
    def model_pair(self) -> dict:
        return dict(self.profile.model_pair)

    def tokenizer(self) -> TextTokenizer:
        with self._tok_lock:
            if self._tokenizer is None:
                self._tokenizer = TextTokenizer(self.profile.tokenizer.path)
            return self._tokenizer

    def process(self, text: str, backend: PairBackend) -> dict:
        tok = self.tokenizer()
        ids, _ = tok.encode(text)
        if len(ids) > self.settings.limits.max_tokens:
            raise JobFailed("too_long", "This text is too long to check in one go.")
        try:
            scored = score_text(text, tok, backend)
        except TextTooShortToScore as exc:
            raise JobFailed("too_short", "This text is too short to check.") from exc
        return Analysis(scored, self.calibration.current(), self.settings.limits, tok).result()

    def authenticated(self, request: Request) -> bool:
        return self.password is None or self.signer.verify(request.cookies.get(COOKIE_NAME))

    def require_auth(self, request: Request) -> None:
        if not self.authenticated(request):
            raise ApiError(401, "auth_required", "Enter the password to use Squint.")


def create_app(
    settings: Settings,
    *,
    backend_factory: Callable[[], PairBackend] | None = None,
    tokenizer: TextTokenizer | None = None,
    password=FROM_KEYCHAIN,
    job_tick_s: float = 1.0,
) -> FastAPI:
    svc = Services(settings, backend_factory, tokenizer, password, job_tick_s)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc.queue.start()
        log.info("squint ready: profile=%s password_required=%s", settings.profile.name, svc.password is not None)
        try:
            yield
        finally:
            svc.queue.stop(unload=True)

    app = FastAPI(title="Squint", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.svc = svc

    # ------------------------------------------------------------------ errors
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.headers, **exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        codes = {404: "not_found", 405: "method_not_allowed"}
        return error_response(exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        return error_response(400, "invalid_request", "The request was not in the expected format.")

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    async def json_body(request: Request) -> dict:
        ctype = request.headers.get("content-type", "")
        if not ctype.lower().startswith("application/json"):
            raise ApiError(400, "invalid_request", "Send JSON with Content-Type: application/json.")
        raw = await read_body_capped(request, settings.max_json_bytes, "too_long", "That request is too large.")
        try:
            data = json.loads(raw or b"null")
        except ValueError:
            raise ApiError(400, "invalid_request", "The request body is not valid JSON.")
        if not isinstance(data, dict):
            raise ApiError(400, "invalid_request", "The request body must be a JSON object.")
        return data

    # ------------------------------------------------------------------ session
    @app.get("/api/session")
    async def session(request: Request):
        return {"authenticated": svc.authenticated(request), "password_required": svc.password is not None}

    @app.post("/api/login")
    async def login(request: Request):
        data = await json_body(request)
        if svc.password is None:
            return Response(status_code=204)
        key = client_key(request)
        wait = max(svc.login_limiter.retry_after(key), svc.login_global.retry_after("*"))
        if wait:
            raise ApiError(429, "rate_limited", "Too many login attempts. Try again later.",
                           headers={"Retry-After": str(wait)}, retry_after_s=wait)
        given = data.get("password")
        if not isinstance(given, str) or not password_matches(given, svc.password):
            svc.login_limiter.hit(key)
            svc.login_global.hit("*")
            raise ApiError(401, "bad_password", "That password isn't right.")
        svc.login_limiter.reset(key)
        resp = Response(status_code=204)
        resp.set_cookie(COOKIE_NAME, svc.signer.issue(), max_age=settings.session_ttl_s, httponly=True,
                        samesite="lax", secure=_is_https(request), path="/")
        return resp

    @app.post("/api/logout")
    async def logout(request: Request):
        resp = Response(status_code=204)
        resp.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=_is_https(request))
        return resp

    # ------------------------------------------------------------------ status / accuracy
    @app.get("/api/status")
    async def status(request: Request):
        svc.require_auth(request)
        cal = svc.calibration.current()
        return {
            "model_state": svc.manager.state,
            "queue_length": svc.queue.queue_length(),
            "model_pair": svc.model_pair,
            "calibration": {"version": cal.version, "ready": cal.ready_for(svc.model_pair)},
            "limits": settings.limits.public(),
        }

    @app.get("/api/accuracy")
    async def accuracy(request: Request):
        svc.require_auth(request)
        report = svc.calibration.current().report
        if report is None:
            raise ApiError(404, "not_calibrated", "The accuracy report isn't ready yet.")
        return report

    # ------------------------------------------------------------------ extract
    @app.post("/api/extract")
    async def extract(request: Request):
        svc.require_auth(request)
        ctype = request.headers.get("content-type", "")
        if not ctype.lower().startswith("multipart/form-data"):
            raise ApiError(415, "unsupported_file", "Upload the file as multipart/form-data in the field 'file'.")
        cap = settings.max_upload_bytes + 64 * 1024
        body = await read_body_capped(request, cap, "file_too_large", "Files can be at most 10 MB.")
        try:
            parsed = parse_multipart_file(ctype, body)
        except Exception:
            parsed = None
        if parsed is None:
            raise ApiError(400, "invalid_request", "No file was found in the field 'file'.")
        filename, data = parsed
        del body
        try:
            text = await run_in_threadpool(extract_text, filename, data, settings.max_upload_bytes)
        except ExtractError as exc:
            raise ApiError(exc.status, exc.code, exc.message)
        return {"text": text, "filename": Path(filename).name, "word_count": count_words(text)}

    # ------------------------------------------------------------------ analyze / jobs
    @app.post("/api/analyze", status_code=202)
    async def analyze(request: Request):
        svc.require_auth(request)
        data = await json_body(request)
        text = data.get("text")
        if not isinstance(text, str):
            raise ApiError(400, "invalid_request", "Send the text to check as {\"text\": \"...\"}.")
        lim = settings.limits
        words = count_words(text)
        if words < lim.min_words:
            raise ApiError(422, "too_short", f"Paste at least {lim.min_words} words. This text has {words}.")
        if words > lim.max_words or len(text) > lim.max_chars:
            raise ApiError(422, "too_long", f"Squint checks up to {lim.max_words:,} words at a time. This text has {words:,}.")
        key = client_key(request)
        wait = svc.analyze_limiter.retry_after(key)
        if wait:
            raise ApiError(429, "rate_limited",
                           f"You've hit the limit of {lim.checks_per_hour} checks an hour. Try again in {max(1, round(wait / 60))} min.",
                           headers={"Retry-After": str(wait)}, retry_after_s=wait)
        try:
            job, position = svc.queue.submit(text, key)
        except QueueFull:
            raise ApiError(503, "busy", "Squint is busy right now. Try again in a minute.")
        svc.analyze_limiter.hit(key)
        return JSONResponse({"job_id": job.id, "position": position}, status_code=202)

    @app.get("/api/jobs/{job_id}")
    async def job(job_id: str, request: Request):
        svc.require_auth(request)
        snap = svc.queue.snapshot(job_id)
        if snap is None:
            raise ApiError(404, "job_not_found", "That check has expired or never existed. Run it again.")
        return snap

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def api_not_found(rest: str):
        raise ApiError(404, "not_found", "No such endpoint.")

    # ------------------------------------------------------------------ web UI
    @app.get("/{path:path}")
    async def web(path: str):
        dist = Path(settings.web_dist)
        index = dist / "index.html"
        if not index.is_file():
            return Response("Squint web UI is not built yet (web/dist).", status_code=404, media_type="text/plain")
        root = dist.resolve()
        target = (dist / path).resolve() if path else index.resolve()
        if path and root in target.parents and target.is_file():
            headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
            media = mimetypes.guess_type(str(target))[0]
            return FileResponse(target, headers=headers, media_type=media)
        if Path(path).suffix:  # a missing file, not a client-side route
            return Response("Not found", status_code=404, media_type="text/plain")
        return FileResponse(index, headers={"Cache-Control": "no-cache"}, media_type="text/html")

    return app
