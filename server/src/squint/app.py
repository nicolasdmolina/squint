"""FastAPI app implementing docs/api-contract.md."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import mimetypes
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from .analysis import Analysis, PreviewAnalysis, TextTooShortToScore, score_text
from .auth import COOKIE_NAME, PasswordMissing, SessionSigner, password_matches, read_keychain_password
from .backend import LlamaCppPair, PairBackend
from .calibration import CalibrationStore
from .clf import ClassifierHolder, config_ok
from .config import REPO_DIR, Settings
from .extract import ExtractError, extract_text
from .jobs import JobFailed, JobQueue, ModelManager, QueueFull
from .ratelimit import SlidingWindowLimiter
from .textproc import TextTokenizer, count_words, valid_unicode

log = logging.getLogger("squint.app")

FROM_KEYCHAIN = object()


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.headers, self.extra = status, code, message, headers, extra


def error_response(status: int, code: str, message: str, headers: dict | None = None, **extra) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status, headers=headers)


def rate_key(addr: str) -> str:
    """Rate-limit key for a client address: IPv4 as is, IPv6 by its /64 (one subscriber's
    allocation, so rotating addresses inside it does not reset the limits)."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return addr[:64] or "unknown"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network(((int(ip) >> 64) << 64, 64)))
    return str(ip)


def client_key(request: Request) -> str:
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    return rate_key(cf or (request.client.host if request.client else "unknown"))


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


class ClassifierOnly:
    """Stands in for the model pair in preview mode: "loading" it loads only the classifier."""

    observer_label = performer_label = ""

    def __init__(self, svc: Services):
        self._svc = svc
        self.clf = None

    @property
    def loaded(self) -> bool:
        return self.clf is not None

    def load(self) -> None:
        self.clf = self._svc.classifier.get(self._svc.calibration.current().classifier)
        if self.clf is None:
            raise RuntimeError("the classifier is not configured or failed to load")

    def unload(self) -> None:
        self.clf = None

    def score_ids(self, ids):
        raise RuntimeError("preview mode has no model pair")


class Services:
    """Everything the routes share; one instance per app."""

    def __init__(self, settings: Settings, backend_factory: Callable[[], PairBackend] | None,
                 tokenizer: TextTokenizer | None, password, job_tick_s: float = 1.0, classifier_factory=None):
        self.settings = settings
        self.profile = settings.profile
        self.calibration = CalibrationStore(settings.calibration_dir)
        self._tokenizer = tokenizer
        self._tok_lock = threading.Lock()
        if settings.mode == "preview":
            password = None  # the public preview is open by design; its limits are the protection
        elif password is FROM_KEYCHAIN:
            password = read_keychain_password(settings.keychain_service)
        if settings.require_password and not password and settings.mode != "preview":
            raise PasswordMissing(f"require_password is on but Keychain item {settings.keychain_service!r} "
                                  "was not found (add it, or set [server].require_password = false)")
        self.password: str | None = password
        self.signer = SessionSigner(settings.session_ttl_s)
        self.analyze_limiter = SlidingWindowLimiter(settings.limits.checks_per_hour, 3600)
        self.extract_limiter = SlidingWindowLimiter(settings.limits.extracts_per_hour, 3600)
        self.extract_slot = threading.Lock()  # one file extraction at a time, server-wide
        self.login_limiter = SlidingWindowLimiter(settings.login_max_failures, settings.login_window_s)
        self.login_global = SlidingWindowLimiter(settings.login_global_max_failures, settings.login_global_window_s)
        pair_factory = backend_factory or (lambda: LlamaCppPair(self.profile))

        def factory():
            if settings.mode == "preview":
                return ClassifierOnly(self)
            # load the classifier first, while memory is still free; the pair takes ~10 GB
            self.classifier.get(self.calibration.current().classifier)
            return pair_factory()

        self.manager = ModelManager(factory, settings.idle_unload_s)
        self.classifier = ClassifierHolder(REPO_DIR, classifier_factory)
        self.manager.on_unload = self.classifier.unload
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
        if isinstance(backend, ClassifierOnly):
            return PreviewAnalysis(text, self.calibration.current(), self.settings.limits, backend.clf).result()
        tok = self.tokenizer()
        ids, _ = tok.encode(text)
        if len(ids) > self.settings.limits.max_tokens:
            raise JobFailed("too_long", "This text is too long to check in one go.")
        try:
            scored = score_text(text, tok, backend)
        except TextTooShortToScore as exc:
            raise JobFailed("too_short", "This text is too short to check.") from exc
        cal = self.calibration.current()
        return Analysis(scored, cal, self.settings.limits, tok, self.classifier.get(cal.classifier)).result()

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
    classifier_factory=None,
) -> FastAPI:
    svc = Services(settings, backend_factory, tokenizer, password, job_tick_s, classifier_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc.queue.start()
        log.info("squint ready: mode=%s profile=%s password_required=%s", settings.mode, settings.profile.name,
                 svc.password is not None)
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
        wait = svc.login_limiter.retry_after(key)
        if wait:
            raise ApiError(429, "rate_limited", "Too many login attempts. Try again later.",
                           headers={"Retry-After": str(wait)}, retry_after_s=wait)
        if svc.login_global.retry_after("*"):
            # many failures from many clients: slow every attempt a little, but never lock out
            # the right password (that would let anyone with a few IPs lock everyone out)
            await asyncio.sleep(settings.login_global_delay_s)
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
            "mode": settings.mode,
            "model_state": svc.manager.state,
            "queue_length": svc.queue.queue_length(),
            "model_pair": svc.model_pair,
            "calibration": {"version": cal.version, "ready": cal.ready_for(svc.model_pair)},
            "classifier": ({"version": cal.classifier.get("version"), "ready": True,
                            "min_words": int(cal.classifier["min_words"])} if config_ok(cal.classifier)
                           else {"version": None, "ready": False, "min_words": None}),
            "limits": settings.limits.public(),
        }

    @app.get("/api/accuracy")
    async def accuracy(request: Request):
        svc.require_auth(request)
        cal = svc.calibration.current()
        report = cal.report_for(svc.model_pair)
        if report is None:
            raise ApiError(404, "not_calibrated", "The accuracy report isn't ready yet.")
        if config_ok(cal.classifier):
            c = cal.classifier
            report = {**report, "classifier": {k: c.get(k) for k in (
                "version", "model", "min_words", "held_out", "by_length")}}
        return report

    # ------------------------------------------------------------------ extract
    @app.post("/api/extract")
    async def extract(request: Request):
        svc.require_auth(request)
        ctype = request.headers.get("content-type", "")
        if not ctype.lower().startswith("multipart/form-data"):
            raise ApiError(415, "unsupported_file", "Upload the file as multipart/form-data in the field 'file'.")
        key = client_key(request)
        wait = svc.extract_limiter.retry_after(key)
        if wait:
            raise ApiError(429, "rate_limited",
                           f"You've hit the limit of {settings.limits.extracts_per_hour} file uploads an hour. "
                           f"Try again in {max(1, round(wait / 60))} min.",
                           headers={"Retry-After": str(wait)}, retry_after_s=wait)
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
        svc.extract_limiter.hit(key)
        deadline = time.monotonic() + settings.extract_wait_s
        while not svc.extract_slot.acquire(blocking=False):
            if time.monotonic() >= deadline:
                raise ApiError(503, "busy", "Squint is reading another file. Try again in a moment.")
            await asyncio.sleep(0.05)
        try:
            # run_in_threadpool waits for the thread even if this request is cancelled, so the
            # slot is only freed once the extraction (and its child process) has finished
            text = await run_in_threadpool(extract_text, filename, data, settings.max_upload_bytes)
        except ExtractError as exc:
            raise ApiError(exc.status, exc.code, exc.message)
        finally:
            svc.extract_slot.release()
        return {"text": text, "filename": Path(filename).name, "word_count": count_words(text)}

    # ------------------------------------------------------------------ analyze / jobs
    @app.post("/api/analyze", status_code=202)
    async def analyze(request: Request):
        svc.require_auth(request)
        data = await json_body(request)
        text = data.get("text")
        if not isinstance(text, str):
            raise ApiError(400, "invalid_request", "Send the text to check as {\"text\": \"...\"}.")
        if not valid_unicode(text):
            raise ApiError(400, "invalid_request", "The text contains characters that aren't valid Unicode.")
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
        # the public site serves its landing page at / and the app under /app/
        if path == "app" or path.startswith("app/"):
            path = path[4:]
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
