"""One night of classifier work, inside a fixed window, yielding the machine to Squint itself.

Started by ops/nightly.sh (launchd, 00:30). It is safe to start at any time: outside the window
it logs and exits; a second copy exits at once (lock); everything resumes where the last night
stopped.

  classifier/.venv/bin/python classifier/nightly.py            # real night
  classifier/.venv/bin/python classifier/nightly.py --stub     # dry run: stages are sleeps

How a night goes (all stages are separate processes in their own process groups):
  1. fetch     human data still missing from data/human_extra.jsonl (network; once, then cached)
  2. plan      extend classifier/generated/plan.jsonl (seconds)
  3. generate  one process per generator (gemini, chatgpt, claude), started together and left
               running in the background for the whole window; each stops at its per-night
               call cap, on auth/usage-limit errors, or 2 minutes before the window ends
  4. build     data/dataset.jsonl from everything generated so far (minutes) -- skipped when
               an unfinished training run is waiting to be resumed
  5. train     heavy: resumes an unfinished run or starts one on the new dataset; must end
               EVAL_RESERVE minutes before the window closes (it checkpoints and exits 3)
  6. evaluate  heavy: the newest finished run without a report -> classifier/reports/<date>.*
  7. wait      for the generators until they finish or the window closes
Heavy stages only start when Squint has no queued checks and no models loaded, no other
heavy job (squint-score) is running, memory and disk are free enough. While one runs the same
checks repeat every POLL seconds; if Squint gets busy the stage is sent SIGTERM (it
checkpoints), and restarted when the machine is free again. At the window end every child gets
SIGTERM, then SIGKILL after a grace period. Exit: 0 all done, 3 stopped (resumable), 1 error.

Environment (defaults in brackets):
  SQUINT_NIGHTLY_START [00:30]  SQUINT_NIGHTLY_END [07:30]
  SQUINT_NIGHTLY_EVAL_RESERVE_MIN [45]   minutes kept free at the end for evaluation
  SQUINT_NIGHTLY_MIN_FREE_PCT [20]       memory_pressure free % needed to start a heavy stage
  SQUINT_NIGHTLY_MIN_FREE_PCT_RUNNING [5]  ... below which a running heavy stage is paused
  SQUINT_NIGHTLY_MIN_DISK_GB [4]         free disk needed to start a heavy stage
  SQUINT_NIGHTLY_MIN_DISK_GB_RUNNING [2] pause a running heavy stage below this (macOS swap grows on disk)
  SQUINT_NIGHTLY_POLL_S [60]             guard interval
  SQUINT_NIGHTLY_TIMEOUTS_TO_PAUSE [3]   slow /api/status answers in a row before a running stage pauses
  SQUINT_NIGHTLY_GRACE_S [90]            SIGTERM -> SIGKILL grace
  SQUINT_NIGHTLY_YIELD_TO [squint-score] comma list of process patterns that pause heavy stages
  SQUINT_NIGHTLY_GENERATORS              comma list; default config.toml [generate].order
  SQUINT_NIGHTLY_SKIP                    comma list of stages to skip (fetch,plan,generate,...)
  SQUINT_STATUS_URL [http://127.0.0.1:8017/api/status]
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clf_common import CLF_DIR, DATA_DIR, REPORTS_DIR, RUNS_DIR, STATE_DIR, load_config  # noqa: E402
import guards  # noqa: E402

EXIT_DONE, EXIT_STOPPED, EXIT_ERROR = 0, 3, 1
PY = sys.executable

STUB = r"""
import signal, sys, time
name, secs, deadline = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
stop = []
signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
print(f"[stub {name}] working for up to {secs:.0f}s", flush=True)
t0 = time.time()
while time.time() - t0 < secs:
    if stop or time.time() > deadline:
        print(f"[stub {name}] stopping ({'SIGTERM' if stop else 'deadline'}), state saved", flush=True)
        sys.exit(3)
    time.sleep(0.5)
print(f"[stub {name}] done", flush=True)
"""


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def log(msg: str) -> None:
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} nightly: {msg}", flush=True)


class Night:
    def __init__(self, args):
        self.args = args
        self.cfg = load_config()
        self.stop_requested = False
        self.children: dict[str, subprocess.Popen] = {}
        self.start = env("SQUINT_NIGHTLY_START", "00:30")
        self.end = env("SQUINT_NIGHTLY_END", "07:30")
        self.eval_reserve = float(env("SQUINT_NIGHTLY_EVAL_RESERVE_MIN", "45")) * 60
        self.min_free = int(env("SQUINT_NIGHTLY_MIN_FREE_PCT", "20"))
        self.min_free_running = int(env("SQUINT_NIGHTLY_MIN_FREE_PCT_RUNNING", "5"))
        self.min_disk = float(env("SQUINT_NIGHTLY_MIN_DISK_GB", "4"))
        self.min_disk_running = float(env("SQUINT_NIGHTLY_MIN_DISK_GB_RUNNING", "2"))
        self.poll = float(env("SQUINT_NIGHTLY_POLL_S", "60"))
        self.timeouts_to_pause = int(env("SQUINT_NIGHTLY_TIMEOUTS_TO_PAUSE", "3"))
        self.status_timeouts = 0
        self.grace = float(env("SQUINT_NIGHTLY_GRACE_S", "90"))
        self.yield_to = [p for p in env("SQUINT_NIGHTLY_YIELD_TO", "squint-score").split(",") if p.strip()]
        self.status_url = env("SQUINT_STATUS_URL", "http://127.0.0.1:8017/api/status")
        gens = env("SQUINT_NIGHTLY_GENERATORS", ",".join(self.cfg["generate"]["order"]))
        self.generators = [g for g in gens.split(",") if g.strip()]
        self.skip = {s for s in env("SQUINT_NIGHTLY_SKIP", "").split(",") if s.strip()}
        self.state_dir: Path = args.state_dir
        self.state_path = self.state_dir / "nightly.json"
        self.state: dict = {}
        self.window_end = 0.0

    # ---- state -----------------------------------------------------------------------------
    def load_state(self, night: str) -> None:
        old = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.state = old if old.get("night") == night else {"night": night, "stages": {}, "history": old.get("history", [])[-30:]}

    def mark(self, stage: str, status: str, **extra) -> None:
        rec = self.state["stages"].setdefault(stage, {})
        rec.update({"status": status, "at": datetime.now().isoformat(timespec="seconds"), **extra})
        tmp = self.state_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.state, indent=2))
            tmp.replace(self.state_path)
        except OSError as e:  # a full disk (swap growth) must not end the night; the next mark retries
            log(f"could not save state: {e}")
        log(f"{stage}: {status}" + (f" {extra}" if extra else ""))

    def done(self, stage: str) -> bool:
        return self.state["stages"].get(stage, {}).get("status") in ("done", "skipped")

    # ---- processes -------------------------------------------------------------------------
    def cmd(self, name: str, real: list[str], stub_secs: float, deadline: float | None = None) -> list[str]:
        if self.args.stub:
            dl = 1e12 if self.args.stub_ignore_deadline else (deadline or self.window_end)
            return [PY, "-c", STUB, name, str(stub_secs), str(dl)]
        return real

    def spawn(self, name: str, argv: list[str]) -> subprocess.Popen:
        shown = "stub" if self.args.stub else " ".join(argv[2:])
        log(f"start {name}: {shown}")
        p = subprocess.Popen(argv, cwd=str(CLF_DIR.parent), start_new_session=True,
                             stdout=sys.stdout, stderr=subprocess.STDOUT)
        self.children[name] = p
        return p

    def terminate(self, name: str, p: subprocess.Popen, grace: float | None = None) -> int:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                p.wait(timeout=grace if grace is not None else self.grace)
            except subprocess.TimeoutExpired:
                log(f"{name} ignored SIGTERM for {self.grace:.0f}s; killing")
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.wait()
        self.children.pop(name, None)
        return p.returncode

    def terminate_all(self) -> None:
        for name, p in list(self.children.items()):
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        t0 = time.time()
        for name, p in list(self.children.items()):
            self.terminate(name, p, grace=max(0.0, self.grace - (time.time() - t0)))

    def time_left(self) -> float:
        return self.window_end - time.time()

    def should_stop(self) -> bool:
        return self.stop_requested or self.time_left() <= 0

    def sleep(self, secs: float) -> None:
        end = time.time() + secs
        while time.time() < end and not self.should_stop():
            time.sleep(min(1.0, end - time.time()))

    # ---- guards ----------------------------------------------------------------------------
    def blocker(self, starting: bool) -> str | None:
        if self.args.stub and self.args.stub_guard is not None:
            return self.args.stub_guard if self.args.stub_guard_file is None or self.args.stub_guard_file.exists() else None
        status = guards.probe_status(self.status_url)
        if status and status.get("_http_error"):
            status = None
        # A running training job slows the server too, so one slow /api/status answer while a
        # stage runs is not proof that someone is waiting; pause only after several in a row.
        timed_out = bool(status and status.get("_timeout"))
        self.status_timeouts = self.status_timeouts + 1 if timed_out else 0
        if timed_out and not starting and self.status_timeouts < self.timeouts_to_pause:
            log(f"Squint /api/status slow ({self.status_timeouts}/{self.timeouts_to_pause}); not pausing yet")
            status = None
        own = {os.getpid(), *(p.pid for p in self.children.values())}
        procs = guards.probe_busy_processes(self.yield_to, own)
        free = guards.probe_memory_free_pct()
        disk = guards.probe_disk_free_gb(str(CLF_DIR))
        return guards.heavy_stage_blocker(status, free, self.min_free if starting else self.min_free_running,
                                          disk, self.min_disk if starting else self.min_disk_running, procs)

    # ---- stages ----------------------------------------------------------------------------
    def run_light(self, stage: str, argv: list[str], stub_secs: float, timeout: float) -> int:
        if stage in self.skip:
            self.mark(stage, "skipped", reason="SQUINT_NIGHTLY_SKIP")
            return 0
        if self.should_stop():
            return EXIT_STOPPED
        self.mark(stage, "running")
        p = self.spawn(stage, self.cmd(stage, argv, stub_secs))
        limit = time.time() + timeout
        while p.poll() is None:
            if self.should_stop() or time.time() > limit:
                rc = self.terminate(stage, p)
                self.mark(stage, "stopped", rc=rc, reason="window end" if not self.stop_requested else "SIGTERM")
                return EXIT_STOPPED
            time.sleep(1)
        self.children.pop(stage, None)
        rc = p.returncode
        self.mark(stage, "done" if rc == 0 else "failed", rc=rc)
        return rc

    def run_heavy(self, stage: str, make_argv, stub_secs: float, deadline: float) -> int:
        """Run a heavy stage, pausing (SIGTERM -> checkpoint) whenever the machine is needed."""
        if stage in self.skip:
            self.mark(stage, "skipped", reason="SQUINT_NIGHTLY_SKIP")
            return 0
        waiting_logged = None
        while True:
            if self.should_stop() or time.time() >= deadline:
                self.mark(stage, "stopped", reason="no time left before its deadline")
                return EXIT_STOPPED
            why = self.blocker(starting=True)
            if why:
                if why != waiting_logged:
                    self.mark(stage, "waiting", reason=why)
                    waiting_logged = why
                self.sleep(self.poll)
                continue
            waiting_logged = None
            self.mark(stage, "running")
            p = self.spawn(stage, self.cmd(stage, make_argv(deadline), stub_secs, deadline))
            paused = None
            next_check = time.time() + self.poll
            while p.poll() is None:
                if self.should_stop():
                    rc = self.terminate(stage, p)
                    self.mark(stage, "stopped", rc=rc, reason="window end" if not self.stop_requested else "SIGTERM")
                    return EXIT_STOPPED
                if time.time() > deadline + self.grace:  # it should have checkpointed and exited by now
                    rc = self.terminate(stage, p)
                    self.mark(stage, "stopped", rc=rc, reason="overran its deadline; sent SIGTERM")
                    return EXIT_STOPPED
                if time.time() >= next_check:
                    next_check = time.time() + self.poll
                    paused = self.blocker(starting=False)
                    if paused:
                        log(f"pausing {stage}: {paused}")
                        self.terminate(stage, p)
                        break
                time.sleep(1)
            self.children.pop(stage, None)
            rc = p.returncode
            if rc == EXIT_DONE:
                self.mark(stage, "done", rc=rc)
                return EXIT_DONE
            if paused:  # we stopped it; even a SIGKILL leaves the last checkpoint to resume from
                self.mark(stage, "paused", reason=paused, rc=rc)
                continue
            if rc == EXIT_STOPPED:
                self.mark(stage, "stopped", rc=rc, reason="stage deadline")
                return EXIT_STOPPED
            self.mark(stage, "failed", rc=rc)
            return EXIT_ERROR

    # ---- helpers for the real stages -------------------------------------------------------
    def unfinished_run(self) -> Path | None:
        runs = [p for p in RUNS_DIR.glob("*/run.json") if not (p.parent / "final" / "trained.json").exists()]
        return max(runs, key=lambda p: p.stat().st_mtime).parent if runs else None

    def run_to_evaluate(self) -> Path | None:
        done = sorted((p.parent.parent for p in RUNS_DIR.glob("*/final/trained.json")),
                      key=lambda p: (p / "final" / "trained.json").stat().st_mtime, reverse=True)
        if not done:
            return None
        reported = set()
        for r in REPORTS_DIR.glob("*.json"):
            try:
                reported.add(json.loads(r.read_text()).get("run"))
            except (ValueError, OSError):
                pass
        return done[0] if done[0].name not in reported else None

    def human_sources_missing(self) -> bool:
        want = {"arxiv", "wikipedia", "amazon-reviews", "stackexchange", "persuade"}
        path = DATA_DIR / "human_extra.jsonl"
        if not path.exists():
            return True
        have = {json.loads(line)["source"] for line in path.open() if line.strip()}
        return not want <= have

    # ---- the night -------------------------------------------------------------------------
    def run(self) -> int:
        now = datetime.now().astimezone()
        bounds = guards.window_bounds(now, self.start, self.end)
        if bounds is None:
            log(f"outside the {self.start}-{self.end} window; nothing to do")
            return EXIT_DONE
        self.window_end = bounds[1].timestamp()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.load_state(bounds[0].date().isoformat())
        log(f"window {bounds[0]:%H:%M}-{bounds[1]:%H:%M}, {self.time_left() / 60:.0f} min left"
            + (" (STUB dry run)" if self.args.stub else ""))
        report_date = bounds[1].date().isoformat()
        train_deadline = self.window_end - self.eval_reserve
        final_rc = EXIT_DONE

        # 1. fetch (network, light)
        if "fetch" in self.skip:
            self.mark("fetch", "skipped", reason="SQUINT_NIGHTLY_SKIP")
        elif self.args.stub or self.human_sources_missing():
            rc = self.run_light("fetch", [PY, "-u", "classifier/fetch_human.py", "fetch"], 2, 45 * 60)
            final_rc = max(final_rc, 0 if rc == 0 else EXIT_STOPPED)  # a failed source is retried next night
        else:
            self.mark("fetch", "skipped", reason="human data complete")

        # 2. plan
        rc = self.run_light("plan", [PY, "-u", "classifier/generate.py", "plan"], 1, 10 * 60)
        plan_ok = rc == 0

        # 3. generators in the background
        gen_deadline = self.window_end - 120
        if "generate" in self.skip or not plan_ok:
            self.mark("generate", "skipped", reason="SQUINT_NIGHTLY_SKIP" if plan_ok else "no plan")
        else:
            for gen in self.generators:
                self.spawn(f"generate-{gen}", self.cmd(
                    f"generate-{gen}",
                    [PY, "-u", "classifier/generate.py", "run", "--source", gen, "--deadline", str(gen_deadline)],
                    self.args.stub_gen_secs, gen_deadline))
            self.mark("generate", "running", generators=self.generators)

        # 4-5. build + train
        resume = None if self.args.stub else self.unfinished_run()
        if resume is not None:
            self.mark("build", "skipped", reason=f"resuming unfinished run {resume.name}")
            train_argv = lambda dl: [PY, "-u", "classifier/train.py", "--run-dir", str(resume), "--deadline", str(dl)]  # noqa: E731
        else:
            rc = self.run_light("build", [PY, "-u", "classifier/build_dataset.py"], 2, 30 * 60)
            if rc != 0:
                final_rc = EXIT_ERROR if rc != EXIT_STOPPED else EXIT_STOPPED
            train_argv = lambda dl: [PY, "-u", "classifier/train.py", "--deadline", str(dl)]  # noqa: E731
        if self.done("build") or resume is not None:
            rc = self.run_heavy("train", train_argv, self.args.stub_train_secs, train_deadline)
            if rc == EXIT_ERROR:
                final_rc = EXIT_ERROR
            elif rc == EXIT_STOPPED:
                final_rc = max(final_rc, EXIT_STOPPED)

        # 6. evaluate the newest finished run that has no report yet
        target = Path("stub") if self.args.stub else self.run_to_evaluate()
        if target is None:
            self.mark("evaluate", "skipped", reason="no finished run without a report")
        else:
            ev = [PY, "-u", "classifier/evaluate.py", "--run-dir", str(target), "--date", report_date]
            rc = self.run_heavy("evaluate", lambda dl: ev + ["--deadline", str(dl)], self.args.stub_eval_secs,
                                self.window_end - 60)
            if rc == EXIT_ERROR:
                final_rc = EXIT_ERROR
            elif rc == EXIT_STOPPED:
                final_rc = max(final_rc, EXIT_STOPPED)

        # 7. let the generators use the rest of the window
        gens = {n: p for n, p in self.children.items() if n.startswith("generate-")}
        if gens:
            log(f"waiting for generators ({', '.join(gens)}) until they finish or the window closes")
        while any(p.poll() is None for p in gens.values()) and not self.should_stop():
            time.sleep(2)
        gen_rcs = {}
        for n, p in gens.items():
            gen_rcs[n] = self.terminate(n, p) if p.poll() is None else p.returncode
            self.children.pop(n, None)
        if gens:
            stopped = any(rc not in (0,) for rc in gen_rcs.values())
            self.mark("generate", "stopped" if stopped else "done", rcs=gen_rcs)
        self.terminate_all()

        summary = {"night": self.state["night"], "report_date": report_date, "exit": final_rc,
                   "stages": self.state["stages"], "stub": self.args.stub}
        self.state["history"] = (self.state.get("history", []) + [{"night": self.state["night"], "exit": final_rc}])[-30:]
        self.mark("night", "finished", exit=final_rc)
        out_dir = self.state_dir if self.args.stub else REPORTS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{report_date}-night.json").write_text(json.dumps(summary, indent=2))
        log(f"night finished with exit {final_rc}; summary -> {out_dir / f'{report_date}-night.json'}")
        return final_rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub", action="store_true", help="dry run: every stage is a short sleep")
    ap.add_argument("--state-dir", type=Path, default=STATE_DIR)
    ap.add_argument("--stub-gen-secs", type=float, default=36000)
    ap.add_argument("--stub-train-secs", type=float, default=36000)
    ap.add_argument("--stub-eval-secs", type=float, default=3)
    ap.add_argument("--stub-ignore-deadline", action="store_true",
                    help="stub only: stages ignore their deadline, so only the window-end SIGTERM stops them")
    ap.add_argument("--stub-guard", default=None, help="stub only: blocker text to report instead of probing")
    ap.add_argument("--stub-guard-file", type=Path, default=None,
                    help="stub only: report --stub-guard only while this file exists")
    args = ap.parse_args()
    if args.stub and args.state_dir == STATE_DIR:
        print("--stub needs its own --state-dir (keeps the real state untouched)", file=sys.stderr)
        return EXIT_ERROR

    args.state_dir.mkdir(parents=True, exist_ok=True)
    lock = open(args.state_dir / "nightly.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another nightly run holds the lock; exiting")
        return EXIT_DONE
    lock.write(str(os.getpid()))
    lock.flush()

    night = Night(args)

    def on_signal(signum, frame):
        night.stop_requested = True
        log(f"received signal {signum}; stopping children")

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    try:
        return night.run()
    except Exception as e:
        log(f"error: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return EXIT_ERROR
    finally:
        night.terminate_all()


if __name__ == "__main__":
    sys.exit(main())
