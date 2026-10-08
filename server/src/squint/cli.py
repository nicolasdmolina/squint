"""Command-line entry points: squint-server, squint-score, squint-models."""

from __future__ import annotations

import argparse
import json
import logging
import os
import resource
import shutil
import socket
import sys
import time
from pathlib import Path

from .config import Settings, load_profiles, load_settings

MIN_FREE_BYTES = 5 * 1024**3


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("SQUINT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # bytes on macOS


# ------------------------------------------------------------------------------ squint-server


def server_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="squint-server", description="Run the Squint detector server.")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--profile", help="model profile from squint.toml (default: [models].profile)")
    args = ap.parse_args(argv)
    _setup_logging()
    settings = load_settings(profile=args.profile)
    host = args.host or settings.host
    port = args.port or settings.port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            sys.exit(f"squint-server: {host}:{port} is already in use")

    import uvicorn

    from .app import create_app
    from .auth import KeychainError

    try:
        app = create_app(settings)
    except KeychainError as exc:
        sys.exit(f"squint-server: {exc}; refusing to start without the password")
    uvicorn.run(app, host=host, port=port, workers=1, log_level="info")


# ------------------------------------------------------------------------------ squint-score


def _read_done_ids(out_path: Path) -> set:
    """Ids already written; drops a truncated trailing line left by an interrupted run."""
    done: set = set()
    if not out_path.exists():
        return done
    good_bytes = 0
    with open(out_path, "rb") as fh:
        for line in fh:
            if not line.endswith(b"\n"):
                break
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                break
            good_bytes += len(line)
    if good_bytes != out_path.stat().st_size:
        with open(out_path, "r+b") as fh:
            fh.truncate(good_bytes)
    return done


def score_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="squint-score",
        description="Score dataset rows with the same code path as the web app "
                    "(docs/calibration-format.md section 2).")
    ap.add_argument("--in", dest="inp", required=True, help="input .jsonl with at least id and text")
    ap.add_argument("--out", required=True, help="output .jsonl, one line per input row, same order")
    ap.add_argument("--resume", action="store_true", help="skip ids already present in --out")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing --out")
    ap.add_argument("--profile", help="model profile from squint.toml")
    ap.add_argument("--limit", type=int, help="stop after this many input rows (testing)")
    ap.add_argument("--progress-every", type=int, default=25)
    args = ap.parse_args(argv)
    _setup_logging()

    from .analysis import Analysis, TextTooShortToScore, score_text
    from .backend import LlamaCppPair
    from .calibration import CalibrationStore
    from .textproc import TextTokenizer

    settings = load_settings(profile=args.profile)
    out_path = Path(args.out)
    if out_path.exists() and not (args.resume or args.overwrite):
        sys.exit(f"squint-score: {out_path} exists; pass --resume to continue it or --overwrite to replace it")
    done = _read_done_ids(out_path) if args.resume else set()
    if args.overwrite and out_path.exists():
        out_path.unlink()

    rows = []
    with open(args.inp, encoding="utf-8") as fh:
        for n, line in enumerate(fh):
            if args.limit is not None and len(rows) >= args.limit:
                break
            if line.strip():
                rows.append(line)
    todo = sum(1 for line in rows if json.loads(line).get("id") not in done)
    print(f"squint-score: {len(rows)} rows, {len(rows) - todo} already done, {todo} to score "
          f"with {settings.profile.name}", file=sys.stderr)
    if todo == 0:
        return

    tok = TextTokenizer(settings.profile.tokenizer.path)
    backend = LlamaCppPair(settings.profile)
    t_load = time.perf_counter()
    backend.load()
    print(f"squint-score: models loaded in {time.perf_counter() - t_load:.1f}s", file=sys.stderr)
    cal = CalibrationStore(settings.calibration_dir).current()
    pair = settings.profile.model_pair

    t0 = time.perf_counter()
    scored_n = 0
    try:
        with open(out_path, "a", encoding="utf-8") as out:
            for line in rows:
                row = json.loads(line)
                rid = row.get("id")
                if rid in done:
                    continue
                text = row.get("text")
                if not isinstance(text, str) or not text.strip():
                    rec = {"id": rid, "error": "missing_text", "score": None, "model_pair": pair}
                else:
                    try:
                        scored = score_text(text, tok, backend)
                        rec = Analysis(scored, cal, settings.limits, None).batch_row(rid)
                    except TextTooShortToScore:
                        rec = {"id": rid, "error": "too_short", "score": None, "model_pair": pair}
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                scored_n += 1
                if scored_n % args.progress_every == 0 or scored_n == todo:
                    el = time.perf_counter() - t0
                    rate = scored_n / el if el else 0
                    eta = (todo - scored_n) / rate if rate else 0
                    print(f"squint-score: {scored_n}/{todo}  {rate:.2f} rows/s  eta {eta / 60:.1f} min  "
                          f"peak rss {_peak_rss_mb():.0f} MB", file=sys.stderr)
    finally:
        backend.unload()


# ------------------------------------------------------------------------------ squint-models


def _human(n: float) -> str:
    return f"{n / 1e9:.2f} GB"


def models_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="squint-models", description="List, download and verify model pairs.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    d = sub.add_parser("download")
    d.add_argument("--profile", required=True)
    d.add_argument("--dry-run", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--profile")
    args = ap.parse_args(argv)
    _setup_logging()
    profiles, raw = load_profiles()
    active = os.environ.get("SQUINT_PROFILE") or (raw.get("models") or {}).get("profile")

    if args.cmd == "list":
        for name, p in profiles.items():
            print(f"{'*' if name == active else ' '} {name}: {p.observer_label} + {p.performer_label}")
            for role, f in (("observer", p.observer), ("performer", p.performer), ("tokenizer", p.tokenizer)):
                size = Path(f.path).stat().st_size if Path(f.path).exists() else None
                print(f"    {role:9} {'present ' + _human(size) if size else 'missing':>16}  {f.path}")
        return

    if args.cmd == "download":
        from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url

        p = profiles.get(args.profile) or sys.exit(f"unknown profile {args.profile!r}")
        plan = []
        for f in (p.tokenizer, p.observer, p.performer):
            if not (f.repo and f.filename):
                sys.exit(f"{f.path}: no repo/filename configured to download from")
            if Path(f.path).name != f.filename:
                sys.exit(f"{f.path}: file name must match the repo file {f.filename}")
            meta = get_hf_file_metadata(hf_hub_url(f.repo, f.filename, revision=f.revision))
            have = Path(f.path).stat().st_size if Path(f.path).exists() else 0
            if have == meta.size:
                print(f"have      {f.path}")
                continue
            plan.append((f, meta.size))
        need = sum(size for _, size in plan)
        target_dir = Path(p.observer.path).parent
        target_dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(target_dir).free
        print(f"to download: {_human(need)}; free now: {_human(free)}; free after: {_human(free - need)}")
        if free - need < MIN_FREE_BYTES:
            sys.exit("refusing: less than 5 GB would be left free on this disk")
        if args.dry_run:
            return
        for f, size in plan:
            print(f"download  {f.repo}/{f.filename} ({_human(size)})")
            got = hf_hub_download(f.repo, f.filename, revision=f.revision, local_dir=str(Path(f.path).parent))
            if Path(got).resolve() != Path(f.path).resolve():
                os.replace(got, f.path)
        return

    if args.cmd == "verify":
        from .backend import LlamaCppPair
        from .textproc import TextTokenizer

        name = args.profile or active
        p = profiles.get(name) or sys.exit(f"unknown profile {name!r}")
        tok = TextTokenizer(p.tokenizer.path)
        pair = LlamaCppPair(p)
        t0 = time.perf_counter()
        pair.load()
        print(f"loaded {name} in {time.perf_counter() - t0:.1f}s: {pair.info}")
        print("observer and performer vocabularies are identical")
        texts = pair.vocab_texts()
        hf = tok.vocab()
        mismatched = [t for t, i in hf.items() if i < len(texts) and texts[i].decode("utf-8", "replace") != t]
        print(f"tokenizer.json vs GGUF vocab: {len(hf)} tokens checked, {len(mismatched)} mismatched")
        sample = "The quick brown fox jumps over the lazy dog. " * 4
        ids, _ = tok.encode(sample)
        t0 = time.perf_counter()
        st = pair.score_ids(ids)
        print(f"sample: {len(ids)} tokens, score {st.reference_score():.4f}, {1000 * (time.perf_counter() - t0):.0f} ms")
        print(f"peak rss {_peak_rss_mb():.0f} MB")
        pair.unload()
        if mismatched:
            sys.exit(f"tokenizer mismatch, e.g. {mismatched[:5]}")
