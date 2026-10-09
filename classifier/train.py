"""Fine-tune the AI-text classifier on the train split (PyTorch, MPS on the Mac mini).

  classifier/.venv/bin/python classifier/train.py                       # settings from config.toml
  classifier/.venv/bin/python classifier/train.py --deadline <unix time> # stop cleanly by then
  # smoke test: tiny model, CPU, a few hundred rows
  classifier/.venv/bin/python classifier/train.py --model prajjwal1/bert-tiny --device cpu \
      --limit-rows 200 --epochs 1 --run-dir /tmp/smoke-run

Run directory (default classifier/runs/<model>-<dataset hash>/):
  run.json             settings, dataset hash, the model actually used (after any fallback)
  dataset.jsonl        snapshot of the dataset the run trains on (evaluate.py uses it too)
  checkpoint/          latest checkpoint: model, optimizer, scheduler, trainer_state.json
  final/               the finished model + tokenizer (written once training completes)
  train.log.jsonl      loss / speed / memory every few steps

Resumable: rerunning the same command continues from checkpoint/. A checkpoint is written
every `checkpoint_every` optimizer steps, on SIGTERM/SIGINT and at --deadline.
Exit codes: 0 finished (final/ exists), 3 stopped early (resume later), 1 error.

Imbalance: every epoch draws training chunks with replacement so that each (label, source)
group carries equal weight inside its label and both labels weigh the same. That keeps one big
corpus (or one generator) from defining what "human" or "AI" means.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import signal
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clf_common import DATA_DIR, RUNS_DIR, load_config  # noqa: E402
from common import read_jsonl, write_json  # noqa: E402

import modeling  # noqa: E402

EXIT_DONE, EXIT_STOPPED, EXIT_ERROR = 0, 3, 1


class Stop:
    requested = False
    reason = ""


def on_signal(signum, frame):
    Stop.requested = True
    Stop.reason = signal.Signals(signum).name


def default_run_dir(model: str, dataset_hash: str) -> Path:
    return RUNS_DIR / f"{model.split('/')[-1].lower()}-{dataset_hash}"


def sampling_weights(rows: list[dict]) -> list[float]:
    """Per-row weight so each (label, source) group sums to the same share within its label and
    each label sums to 0.5."""
    groups = Counter((r["y"], r["source"]) for r in rows)
    per_label = Counter(y for (y, _s) in groups)
    return [0.5 / per_label[r["y"]] / groups[(r["y"], r["source"])] for r in rows]


def save_checkpoint(run_dir: Path, model, tok, optimizer, scheduler, state: dict) -> None:
    import torch

    tmp = run_dir / "checkpoint.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    model.save_pretrained(tmp)
    tok.save_pretrained(tmp)
    torch.save(optimizer.state_dict(), tmp / "optimizer.pt")
    torch.save(scheduler.state_dict(), tmp / "scheduler.pt")
    write_json(tmp / "trainer_state.json", state)
    final = run_dir / "checkpoint"
    old = run_dir / "checkpoint.old"
    if final.exists():
        final.rename(old)
    tmp.rename(final)
    if old.exists():
        shutil.rmtree(old)  # previous checkpoint written by this script


def log(run_dir: Path, rec: dict) -> None:
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}
    print(json.dumps(rec), flush=True)
    with open(run_dir / "train.log.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")


def main() -> int:
    cfg = load_config()
    tc = cfg["train"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, default=DATA_DIR / "dataset.jsonl")
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--model", default=tc["model"])
    ap.add_argument("--fallback-model", default=tc["fallback_model"])
    ap.add_argument("--max-length", type=int, default=tc["max_length"])
    ap.add_argument("--max-chunks-per-doc", type=int, default=tc["max_chunks_per_doc"])
    ap.add_argument("--batch-size", type=int, default=tc["batch_size"])
    ap.add_argument("--grad-accum", type=int, default=tc["grad_accum"])
    ap.add_argument("--epochs", type=float, default=tc["epochs"])
    ap.add_argument("--lr", type=float, default=tc["lr"])
    ap.add_argument("--weight-decay", type=float, default=tc["weight_decay"])
    ap.add_argument("--warmup-frac", type=float, default=tc["warmup_frac"])
    ap.add_argument("--checkpoint-every", type=int, default=tc["checkpoint_every"])
    ap.add_argument("--max-steps", type=int, default=None, help="cap on optimizer steps (smoke tests)")
    ap.add_argument("--amp", default=tc["amp"], choices=["auto", "bf16", "fp16", "none"])
    ap.add_argument("--device", default="auto")
    ap.add_argument("--seed", type=int, default=tc["seed"])
    ap.add_argument("--deadline", type=float, default=None, help="unix time to checkpoint and stop by")
    ap.add_argument("--limit-rows", type=int, default=None, help="use only N training rows (smoke tests)")
    args = ap.parse_args()

    # handle SIGTERM from the start: a stop during the slow imports / model load still exits 3
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    modeling.set_mps_memory_cap(tc["mps_memory_fraction"])
    import torch
    from transformers import get_linear_schedule_with_warmup

    # ---- run directory and dataset snapshot ---------------------------------------------
    manifest_path = args.dataset.with_name("dataset-manifest.json")
    if args.run_dir and (args.run_dir / "run.json").exists():
        run_dir = args.run_dir
    else:
        if not args.dataset.exists():
            print(f"no dataset at {args.dataset}; run build_dataset.py first", file=sys.stderr)
            return EXIT_ERROR
        dhash = json.loads(manifest_path.read_text())["dataset_hash"] if manifest_path.exists() else "nohash"
        run_dir = args.run_dir or default_run_dir(args.model, dhash)
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "final" / "config.json").exists():
        print(f"{run_dir} already finished; nothing to do")
        return EXIT_DONE
    run_json = run_dir / "run.json"
    if run_json.exists():
        run = json.loads(run_json.read_text())
        print(f"resuming run {run_dir.name} (model {run['model_used']})", flush=True)
    else:
        shutil.copyfile(args.dataset, run_dir / "dataset.jsonl")
        dhash = json.loads(manifest_path.read_text())["dataset_hash"] if manifest_path.exists() else "nohash"
        run = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "dataset_hash": dhash,
               "model_requested": args.model, "model_used": None, "fallback_reason": None,
               "settings": {k: v for k, v in vars(args).items() if k not in ("dataset", "run_dir", "deadline")}}
    s = run["settings"]  # a resumed run keeps its original settings
    device = modeling.pick_device(s.get("device") or args.device)
    modeling.seed_everything(s["seed"])

    rows = [r for r in read_jsonl(run_dir / "dataset.jsonl") if r["split"] == "train"]
    if s.get("limit_rows"):
        rows = sorted(rows, key=lambda r: hash_key(r["id"]))[: s["limit_rows"]]
    if len({r["y"] for r in rows}) < 2:
        print("training split needs both human and AI rows", file=sys.stderr)
        return EXIT_ERROR

    # ---- model (with the MPS fallback) ---------------------------------------------------
    amp = s["amp"]
    model_name = run["model_used"] or s["model"]
    ckpt = run_dir / "checkpoint"
    if ckpt.exists():
        tok, model = modeling.load_model(model_name, path=str(ckpt))
    else:
        tried = []
        for cand in ([model_name] if run["model_used"] else [s["model"], s["fallback_model"]]):
            try:
                tok, model = modeling.load_model(cand)
                amp_try = ["bf16", "none"] if amp == "auto" and device.type == "mps" else (
                    ["none"] if amp == "auto" else [amp])
                last = None
                for a in amp_try:
                    try:
                        modeling.smoke_step(model, tok, device, a, s["max_length"])
                        amp = a
                        last = None
                        break
                    except Exception as e:  # this precision misbehaves here; try the next one
                        last = e
                if last:
                    raise last
                model_name = cand
                break
            except Exception as e:
                tried.append(f"{cand}: {type(e).__name__}: {e}"[:500])
                print(f"model {cand} failed on {device}: {e}", flush=True)
        else:
            print("no model worked:\n" + "\n".join(tried), file=sys.stderr)
            return EXIT_ERROR
        run["model_used"], run["amp_used"] = model_name, amp
        run["fallback_reason"] = tried[0] if tried else None
        write_json(run_json, run)
    amp = run.get("amp_used", amp)
    model.to(device)

    # ---- chunks, schedule, optimizer -------------------------------------------------------
    chunks, labels, row_of = [], [], []
    for i, r in enumerate(rows):
        for c in modeling.text_chunks(tok, r["text"], s["max_length"], s["max_chunks_per_doc"]):
            chunks.append(c)
            labels.append(r["y"])
            row_of.append(i)
    w_row = sampling_weights(rows)
    n_per_row = Counter(row_of)
    weights = torch.tensor([w_row[i] / n_per_row[i] for i in row_of], dtype=torch.double)
    per_epoch = math.ceil(len(chunks) / s["batch_size"])
    total_micro = int(per_epoch * s["epochs"])
    total_steps = max(1, total_micro // s["grad_accum"])
    if s.get("max_steps"):
        total_steps = min(total_steps, s["max_steps"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=s["lr"], weight_decay=s["weight_decay"])
    scheduler = get_linear_schedule_with_warmup(optimizer, int(total_steps * s["warmup_frac"]), total_steps)
    state = {"opt_step": 0, "model": model_name, "amp": amp}
    if ckpt.exists():
        optimizer.load_state_dict(torch.load(ckpt / "optimizer.pt", map_location=device))
        scheduler.load_state_dict(torch.load(ckpt / "scheduler.pt"))
        state = json.loads((ckpt / "trainer_state.json").read_text())
    log(run_dir, {"event": "start", "device": str(device), "amp": amp, "model": model_name, "rows": len(rows),
                  "chunks": len(chunks), "total_steps": total_steps, "from_step": state["opt_step"]})

    def order_for_epoch(epoch: int) -> list[int]:
        g = torch.Generator().manual_seed(s["seed"] * 1000 + epoch)
        return torch.multinomial(weights, len(chunks), replacement=True, generator=g).tolist()

    # ---- loop ------------------------------------------------------------------------------
    model.train()
    opt_step = state["opt_step"]
    micro = opt_step * s["grad_accum"]
    t0, loss_acc, n_acc, logged_at = time.time(), 0.0, 0, opt_step
    epoch_cache: dict[int, list[int]] = {}
    status = EXIT_DONE
    while opt_step < total_steps:
        epoch, k = divmod(micro, per_epoch)
        if epoch not in epoch_cache:
            epoch_cache = {epoch: order_for_epoch(epoch)}
        idx = epoch_cache[epoch][k * s["batch_size"]:(k + 1) * s["batch_size"]]
        ids, mask = modeling.collate([chunks[i] for i in idx], tok.pad_token_id or 0, device)
        y = torch.tensor([labels[i] for i in idx], device=device)
        with modeling.autocast(device, amp):
            out = model(input_ids=ids, attention_mask=mask, labels=y)
        (out.loss / s["grad_accum"]).backward()
        loss_acc += out.loss.item()
        n_acc += 1
        micro += 1
        if micro % s["grad_accum"] == 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            opt_step += 1
            if opt_step % 20 == 0 or opt_step == total_steps:
                mem = torch.mps.driver_allocated_memory() / 1e9 if device.type == "mps" else None
                log(run_dir, {"step": opt_step, "of": total_steps, "loss": round(loss_acc / n_acc, 4),
                              "lr": scheduler.get_last_lr()[0],
                              "s_per_step": round((time.time() - t0) / max(1, opt_step - logged_at), 2),
                              "mps_gb": round(mem, 2) if mem is not None else None})
                t0, loss_acc, n_acc, logged_at = time.time(), 0.0, 0, opt_step
            if opt_step % s["checkpoint_every"] == 0 and opt_step < total_steps:
                save_checkpoint(run_dir, model, tok, optimizer, scheduler, {**state, "opt_step": opt_step})
        late = args.deadline is not None and time.time() > args.deadline
        if (Stop.requested or late) and opt_step < total_steps:
            # discard the partial accumulation; resume repeats those micro-batches exactly
            optimizer.zero_grad(set_to_none=True)
            save_checkpoint(run_dir, model, tok, optimizer, scheduler, {**state, "opt_step": opt_step})
            log(run_dir, {"event": "stopped", "reason": Stop.reason or "deadline", "step": opt_step,
                          "of": total_steps})
            status = EXIT_STOPPED
            break
    if status == EXIT_DONE:
        final = run_dir / "final"
        model.save_pretrained(final)
        tok.save_pretrained(final)
        write_json(final / "trained.json", {"finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                            "steps": opt_step, "model": model_name, "amp": amp,
                                            "dataset_hash": run["dataset_hash"], "train_rows": len(rows)})
        if ckpt.exists():
            shutil.rmtree(ckpt)  # the optimizer state is ~2x the model; final/ supersedes it
        log(run_dir, {"event": "finished", "steps": opt_step})
    return status


def hash_key(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode()).hexdigest()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # make the failure visible to the nightly runner
        import traceback

        traceback.print_exc()
        sys.exit(EXIT_ERROR)
