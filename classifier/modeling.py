"""Torch helpers shared by train.py and evaluate.py: device, mixed precision, model loading
with the ModernBERT -> DeBERTa fallback, chunked inputs and chunk-averaged predictions.

Import this only after setting PYTORCH_MPS_HIGH_WATERMARK_RATIO (see set_mps_memory_cap).
"""

from __future__ import annotations

import contextlib
import os
import random

from textchunks import chunk_token_ids, weighted_mean


def set_mps_memory_cap(fraction: float) -> None:
    """Hard cap on MPS memory (fraction of the recommended working set). Must run before
    torch is imported. An explicit environment value wins."""
    os.environ.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", str(fraction))
    # the low watermark (default 1.4) must not exceed the high one, or MPS refuses to start
    high = float(os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"])
    os.environ.setdefault("PYTORCH_MPS_LOW_WATERMARK_RATIO", str(round(high * 0.8, 3)))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def pick_device(name: str = "auto"):
    import torch

    if name == "auto":
        return torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    return torch.device(name)


def seed_everything(seed: int) -> None:
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def autocast(device, amp: str):
    import torch

    if amp in ("bf16", "fp16") and device.type in ("mps", "cuda", "cpu"):
        dtype = torch.bfloat16 if amp == "bf16" else torch.float16
        return torch.autocast(device_type=device.type, dtype=dtype)
    return contextlib.nullcontext()


def load_model(name: str, num_labels: int = 2, path: str | None = None):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    src = path or name
    kw = {"num_labels": num_labels}
    if "modernbert" in name.lower():
        kw["attn_implementation"] = "sdpa"  # no flash-attn on Apple silicon
    try:
        tok = AutoTokenizer.from_pretrained(src)
        model = AutoModelForSequenceClassification.from_pretrained(src, **kw)
    except (ValueError, KeyError):
        # old BERT uploads (e.g. prajjwal1/bert-tiny, the smoke-test model) ship a config without
        # model_type; load them with the BERT classes explicitly
        from transformers import BertConfig, BertForSequenceClassification, BertTokenizerFast

        tok = BertTokenizerFast.from_pretrained(src)
        config = BertConfig.from_pretrained(src, num_labels=num_labels)
        model = BertForSequenceClassification.from_pretrained(src, config=config)
    return tok, model


_TEMPLATES: dict[int, tuple[list[int], list[int]]] = {}


def special_template(tok) -> tuple[list[int], list[int]]:
    """(prefix, suffix) special-token ids the tokenizer wraps one sequence in, e.g. [CLS] / [SEP].
    Derived by encoding a probe text with and without special tokens (transformers 5 dropped
    build_inputs_with_special_tokens from fast tokenizers)."""
    cached = _TEMPLATES.get(id(tok))
    if cached is not None:
        return cached
    probe = "hello"
    bare = tok(probe, add_special_tokens=False)["input_ids"]
    full = tok(probe, add_special_tokens=True)["input_ids"]
    for i in range(len(full) - len(bare) + 1):
        if full[i:i + len(bare)] == bare:
            out = (list(full[:i]), list(full[i + len(bare):]))
            break
    else:
        raise RuntimeError("cannot work out the tokenizer's special-token template")
    _TEMPLATES[id(tok)] = out
    return out


def special_count(tok) -> int:
    pre, suf = special_template(tok)
    return len(pre) + len(suf)


def text_chunks(tok, text: str, max_length: int, max_chunks: int | None) -> list[list[int]]:
    ids = tok(text, add_special_tokens=False)["input_ids"]
    pre, suf = special_template(tok)
    body = max_length - len(pre) - len(suf)
    return [pre + c + suf for c in chunk_token_ids(ids, body, max_chunks)]


def collate(batch_ids: list[list[int]], pad_id: int, device):
    import torch

    n = max(len(x) for x in batch_ids)
    ids = torch.full((len(batch_ids), n), pad_id, dtype=torch.long)
    mask = torch.zeros((len(batch_ids), n), dtype=torch.long)
    for i, x in enumerate(batch_ids):
        ids[i, :len(x)] = torch.tensor(x, dtype=torch.long)
        mask[i, :len(x)] = 1
    return ids.to(device), mask.to(device)


def smoke_step(model, tok, device, amp: str, max_length: int) -> None:
    """One forward + backward on a tiny batch; raises if the model misbehaves on this device."""
    import torch

    model.to(device).train()
    ids, mask = collate([text_chunks(tok, "A short smoke test sentence. " * 40, max_length, 1)[0]] * 2,
                        tok.pad_token_id or 0, device)
    with autocast(device, amp):
        out = model(input_ids=ids, attention_mask=mask, labels=torch.tensor([0, 1], device=device))
    if not torch.isfinite(out.loss):
        raise RuntimeError(f"non-finite loss {out.loss.item()} in smoke step")
    out.loss.backward()
    model.zero_grad(set_to_none=True)


def predict_texts(model, tok, texts: list[str], device, max_length: int, batch_size: int, amp: str = "none",
                  max_chunks: int | None = 8) -> list[float]:
    """P(AI) per text: chunk probabilities averaged, weighted by chunk length."""
    import torch

    model.to(device).eval()
    items = []  # (text index, chunk ids)
    for ti, t in enumerate(texts):
        for c in text_chunks(tok, t, max_length, max_chunks):
            items.append((ti, c))
    order = sorted(range(len(items)), key=lambda i: len(items[i][1]))  # similar lengths -> less padding
    probs = [0.0] * len(items)
    with torch.no_grad():
        for s in range(0, len(order), batch_size):
            idx = order[s:s + batch_size]
            ids, mask = collate([items[i][1] for i in idx], tok.pad_token_id or 0, device)
            with autocast(device, amp):
                logits = model(input_ids=ids, attention_mask=mask).logits.float()
            p = torch.softmax(logits, dim=-1)[:, 1].cpu().tolist()
            for i, v in zip(idx, p):
                probs[i] = v
    per_text: dict[int, tuple[list[float], list[float]]] = {}
    for (ti, c), p in zip(items, probs):
        vs, ws = per_text.setdefault(ti, ([], []))
        vs.append(p)
        ws.append(len(c))
    return [weighted_mean(*per_text[i]) for i in range(len(texts))]
