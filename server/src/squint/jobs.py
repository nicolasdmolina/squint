"""Single-worker job queue and the lazily loaded model pair. Everything lives in memory."""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from .backend import PairBackend

log = logging.getLogger("squint.jobs")


class ModelManager:
    """Loads the pair on first use and unloads it after `idle_unload_s` without work."""

    def __init__(self, factory: Callable[[], PairBackend], idle_unload_s: float, clock=time.monotonic):
        self._factory = factory
        self._idle = idle_unload_s
        self._clock = clock
        self._lock = threading.Lock()
        self._backend: PairBackend | None = None
        self._busy = False
        self.state = "unloaded"  # unloaded | loading | ready (read without the lock)
        self._last_used = clock()
        self.loads = 0
        self.unloads = 0
        self.on_unload: Callable[[], None] | None = None  # also drop models loaded alongside the pair

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def acquire(self) -> tuple[PairBackend, float]:
        """Return (backend, load_ms). Loads the pair if needed. Call `release()` afterwards."""
        with self._lock:
            self._busy = True
            load_ms = 0.0
            if self._backend is None:
                self.state = "loading"
                t0 = time.perf_counter()
                try:
                    backend = self._factory()
                    backend.load()
                except BaseException:
                    self.state = "unloaded"
                    self._busy = False
                    raise
                self._backend = backend
                self.loads += 1
                load_ms = (time.perf_counter() - t0) * 1000.0
                self.state = "ready"
            return self._backend, load_ms

    def release(self) -> None:
        with self._lock:
            self._busy = False
            self._last_used = self._clock()

    def idle_for(self) -> float:
        return self._clock() - self._last_used

    def unload_due(self) -> bool:
        """Cheap unlocked check; `maybe_unload` checks again under the lock."""
        return self._backend is not None and not self._busy and self.idle_for() >= self._idle

    def maybe_unload(self) -> bool:
        if not self.unload_due():
            return False
        with self._lock:
            if not self.unload_due():
                return False
            self._unload_locked()
            return True

    def unload(self) -> bool:
        """Unload now unless a job is using the pair (freeing it mid-score would crash llama.cpp)."""
        with self._lock:
            if self._backend is None:
                return False
            if self._busy:
                log.warning("not unloading the model pair: a job is still using it")
                return False
            self._unload_locked()
            return True

    def _unload_locked(self) -> None:
        backend, self._backend = self._backend, None
        try:
            backend.unload()
            if self.on_unload is not None:
                self.on_unload()
        finally:
            self.state = "unloaded"
            self.unloads += 1
            log.info("model pair unloaded after %.0f s idle", self.idle_for())


class QueueFull(Exception):
    pass


class JobFailed(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Job:
    id: str
    text: str
    client: str
    created: float
    status: str = "queued"
    started: float | None = None
    finished: float | None = None
    result: dict | None = None
    error: dict | None = None


class JobQueue:
    def __init__(
        self,
        process: Callable[[str, PairBackend], dict],
        manager: ModelManager,
        *,
        result_ttl_s: float = 600.0,
        max_queue: int = 50,
        tick_s: float = 1.0,
        clock=time.monotonic,
    ):
        self._process = process
        self.manager = manager
        self._ttl = result_ttl_s
        self._max_queue = max_queue
        self._tick = tick_s
        self._clock = clock
        self._cv = threading.Condition()
        self._jobs: dict[str, Job] = {}
        self._pending: deque[Job] = deque()
        self._running: Job | None = None
        self._unloading = False  # the janitor is unloading the idle pair; the worker waits
        self._stop = False
        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._threads:
            return
        self._stop = False
        for target, name in ((self._worker, "squint-worker"), (self._janitor, "squint-janitor")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, unload: bool = True, join_timeout: float = 30.0) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        for t in self._threads:
            t.join(timeout=join_timeout)
        stuck = [t.name for t in self._threads if t.is_alive()]
        self._threads = []
        if stuck:
            # the worker may still be inside llama.cpp: unloading now would free the context under it
            log.warning("%s still running after %.0f s; leaving the model pair loaded", ", ".join(stuck), join_timeout)
            return
        if unload:
            self.manager.unload()

    # ------------------------------------------------------------------ API
    def submit(self, text: str, client: str) -> tuple[Job, int]:
        with self._cv:
            if len(self._pending) >= self._max_queue:
                raise QueueFull()
            job = Job(id="j_" + secrets.token_urlsafe(12), text=text, client=client, created=self._clock())
            self._jobs[job.id] = job
            self._pending.append(job)
            position = self._position_locked(job)
            self._cv.notify_all()
            return job, position

    def _position_locked(self, job: Job) -> int:
        if job.status != "queued":
            return 0
        ahead = 1 if self._running is not None else 0
        for i, j in enumerate(self._pending):
            if j is job:
                return ahead + i
        return 0

    def snapshot(self, job_id: str) -> dict | None:
        with self._cv:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {
                "job_id": job.id,
                "status": job.status,
                "position": self._position_locked(job),
                "result": job.result,
                "error": job.error,
            }

    def queue_length(self) -> int:
        with self._cv:
            return len(self._pending) + (1 if self._running is not None else 0)

    # ------------------------------------------------------------------ threads
    def _worker(self) -> None:
        while True:
            with self._cv:
                while (not self._pending or self._unloading) and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                job = self._pending.popleft()
                self._running = job
                job.started = self._clock()
                job.status = "scoring" if self.manager.ready else "loading_model"
            self._run(job)
            with self._cv:
                self._running = None
                job.text = ""  # drop the submitted text as soon as it is scored
                self._cv.notify_all()

    def _run(self, job: Job) -> None:
        load_ms = 0.0
        acquired = False
        try:
            backend, load_ms = self.manager.acquire()
            acquired = True
            with self._cv:
                job.status = "scoring"
            t0 = time.perf_counter()
            result = self._process(job.text, backend)
            score_ms = (time.perf_counter() - t0) * 1000.0
            result["timing_ms"] = {
                "queue": round((job.started - job.created) * 1000.0),
                "load": round(load_ms),
                "score": round(score_ms),
            }
            with self._cv:
                job.result = result
                job.status = "done"
        except JobFailed as exc:
            self._fail(job, exc.code, exc.message)
        except Exception as exc:  # never let one job kill the worker
            log.exception("job %s failed", job.id)
            code = "model_unavailable" if not acquired else "scoring_failed"
            msg = ("The detector models could not be loaded." if not acquired
                   else "Something went wrong while scoring this text.")
            self._fail(job, code, msg)
            del exc
        finally:
            if acquired:
                self.manager.release()
            with self._cv:
                job.finished = self._clock()

    def _fail(self, job: Job, code: str, message: str) -> None:
        with self._cv:
            job.error = {"code": code, "message": message}
            job.status = "error"

    def _janitor(self) -> None:
        while True:
            with self._cv:
                self._cv.wait(timeout=self._tick)
                if self._stop:
                    return
                now = self._clock()
                expired = [jid for jid, j in self._jobs.items()
                           if j.finished is not None and now - j.finished >= self._ttl]
                for jid in expired:
                    del self._jobs[jid]
                # decide under the queue lock and hold the worker off until the unload is done:
                # otherwise it could pick up a job in between, label it "scoring" and then have the
                # pair unloaded under it. New jobs still queue meanwhile (submit is not blocked).
                unload_now = not self._pending and self._running is None and self.manager.unload_due()
                self._unloading = unload_now
            if unload_now:
                try:
                    self.manager.maybe_unload()
                except Exception:
                    log.exception("unloading the model pair failed")
                finally:
                    with self._cv:
                        self._unloading = False
                        self._cv.notify_all()
