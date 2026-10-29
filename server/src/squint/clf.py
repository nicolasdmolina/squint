"""The trained AI-text classifier (classifier/ in the repo): ModernBERT fine-tuned on human
writing and ChatGPT / Claude output. It decides the verdict for texts of `min_words`+ words;
Binoculars still supplies the word-level view.

calibration/classifier.json (written by classifier/promote.py) names the model directory and
the cutoffs. Inference copies classifier/modeling.py's predict_texts exactly: the text is
tokenised once, cut into windows of max_length tokens (at most max_chunks, evenly spaced) and
the chunk probabilities are averaged, weighted by chunk length.

torch is imported lazily so the server starts (and its tests run) without loading it.
"""

from __future__ import annotations

import logging
import math
import threading
from pathlib import Path

log = logging.getLogger("squint.clf")


def config_ok(cfg: dict | None) -> bool:
    if not isinstance(cfg, dict):
        return False
    nums = ("ai_above", "human_below", "min_words", "max_length", "max_chunks")
    return (isinstance(cfg.get("path"), str)
            and all(isinstance(cfg.get(k), (int, float)) and not isinstance(cfg.get(k), bool)
                    and math.isfinite(cfg[k]) for k in nums)
            and cfg["human_below"] <= cfg["ai_above"])


def chunk_token_ids(ids: list[int], body_len: int, max_chunks: int | None = None) -> list[list[int]]:
    """Same as classifier/textchunks.py (kept in sync by tests/test_clf.py)."""
    if body_len <= 0:
        raise ValueError("body_len must be positive")
    if len(ids) <= body_len:
        return [list(ids)]
    chunks = [ids[i:i + body_len] for i in range(0, len(ids), body_len)]
    if len(chunks[-1]) < body_len // 4:
        chunks[-1] = ids[-body_len:]
    if max_chunks and len(chunks) > max_chunks:
        if max_chunks == 1:
            return [chunks[0]]
        n = len(chunks)
        idx = sorted({round(i * (n - 1) / (max_chunks - 1)) for i in range(max_chunks)})
        chunks = [chunks[i] for i in idx]
    return [list(c) for c in chunks]


def weighted_mean(values: list[float], weights: list[float]) -> float:
    tw = sum(weights)
    return sum(v * w for v, w in zip(values, weights)) / tw if tw else sum(values) / len(values)


class AiClassifier:
    """Loaded on the first check, unloaded together with the Binoculars pair."""

    def __init__(self, model_dir: Path, max_length: int, max_chunks: int, batch_size: int = 4):
        self.model_dir = Path(model_dir)
        self.max_length = max_length
        self.max_chunks = max_chunks
        self.batch_size = batch_size
        self._tok = None
        self._model = None
        self._template: tuple[list[int], list[int]] | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        self._tok = AutoTokenizer.from_pretrained(str(self.model_dir))
        self._model = AutoModelForSequenceClassification.from_pretrained(
            str(self.model_dir), attn_implementation="sdpa").eval()
        pre_suf = self._special_template()
        self._template = pre_suf
        log.info("classifier loaded from %s", self.model_dir)

    def unload(self) -> None:
        self._model = None
        self._tok = None
        import gc

        gc.collect()

    def _special_template(self) -> tuple[list[int], list[int]]:
        tok = self._tok
        bare = tok("hello", add_special_tokens=False)["input_ids"]
        full = tok("hello", add_special_tokens=True)["input_ids"]
        for i in range(len(full) - len(bare) + 1):
            if full[i:i + len(bare)] == bare:
                return list(full[:i]), list(full[i + len(bare):])
        raise RuntimeError("cannot work out the tokenizer's special-token template")

    def predict(self, texts: list[str]) -> list[float]:
        """P(AI) per text, on the CPU (the GPU belongs to the Binoculars pair). bf16 would halve
        the weights but runs many times slower on the M4's CPU, so it stays fp32. Batches of 4
        chunks were faster and lighter than 8 on a 2,500-word check (2.3 s, ~600 MB peak)."""
        import torch

        if self._model is None:
            raise RuntimeError("classifier not loaded")
        pre, suf = self._template
        body = self.max_length - len(pre) - len(suf)
        items: list[tuple[int, list[int]]] = []
        for ti, t in enumerate(texts):
            ids = self._tok(t, add_special_tokens=False)["input_ids"]
            for c in chunk_token_ids(ids, body, self.max_chunks):
                items.append((ti, pre + c + suf))
        order = sorted(range(len(items)), key=lambda i: len(items[i][1]))
        probs = [0.0] * len(items)
        pad = self._tok.pad_token_id or 0
        with torch.inference_mode():
            for s in range(0, len(order), self.batch_size):
                idx = order[s:s + self.batch_size]
                n = max(len(items[i][1]) for i in idx)
                ids = torch.full((len(idx), n), pad, dtype=torch.long)
                mask = torch.zeros((len(idx), n), dtype=torch.long)
                for row, i in enumerate(idx):
                    x = items[i][1]
                    ids[row, :len(x)] = torch.tensor(x, dtype=torch.long)
                    mask[row, :len(x)] = 1
                logits = self._model(input_ids=ids, attention_mask=mask).logits.float()
                for i, v in zip(idx, torch.softmax(logits, dim=-1)[:, 1].tolist()):
                    probs[i] = v
        per: dict[int, tuple[list[float], list[float]]] = {}
        for (ti, c), p in zip(items, probs):
            vs, ws = per.setdefault(ti, ([], []))
            vs.append(p)
            ws.append(len(c))
        return [weighted_mean(*per[i]) for i in range(len(texts))]


class OnnxClassifier:
    """The same classifier exported to model.onnx (squint.onnx_export), run with onnxruntime and
    the tokenizers library: no torch, about 1 GB of memory. Used by the cloud preview server.
    Windows run one at a time, so no padding ever reaches the model."""

    def __init__(self, model_dir: Path, max_length: int, max_chunks: int, threads: int | None = None):
        self.model_dir = Path(model_dir)
        self.max_length = max_length
        self.max_chunks = max_chunks
        self.threads = threads
        self._tok = None
        self._session = None
        self._template: tuple[list[int], list[int]] | None = None

    @property
    def loaded(self) -> bool:
        return self._session is not None

    def load(self) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = self.threads or 0
        self._session = ort.InferenceSession(str(self.model_dir / ONNX_FILE), opts,
                                             providers=["CPUExecutionProvider"])
        self._tok = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
        self._tok.no_truncation()
        self._tok.no_padding()
        bare = self._tok.encode("hello", add_special_tokens=False).ids
        full = self._tok.encode("hello", add_special_tokens=True).ids
        for i in range(len(full) - len(bare) + 1):
            if full[i:i + len(bare)] == bare:
                self._template = (list(full[:i]), list(full[i + len(bare):]))
                break
        else:
            raise RuntimeError("cannot work out the tokenizer's special-token template")
        log.info("classifier loaded from %s (onnx)", self.model_dir)

    def unload(self) -> None:
        self._session = None
        self._tok = None

    def predict(self, texts: list[str]) -> list[float]:
        import numpy as np

        if self._session is None:
            raise RuntimeError("classifier not loaded")
        pre, suf = self._template
        body = self.max_length - len(pre) - len(suf)
        out = []
        for t in texts:
            ids = self._tok.encode(t, add_special_tokens=False).ids
            probs, weights = [], []
            for c in chunk_token_ids(ids, body, self.max_chunks):
                x = np.array([pre + c + suf], dtype=np.int64)
                logits = self._session.run(None, {"input_ids": x, "attention_mask": np.ones_like(x)})[0][0]
                z = logits.astype(np.float64) - logits.max()
                probs.append(float(np.exp(z[1]) / np.exp(z).sum()))
                weights.append(len(c))
            out.append(weighted_mean(probs, weights))
        return out


ONNX_FILE = "model.onnx"


def make_classifier(model_dir: Path, max_length: int, max_chunks: int):
    """ONNX when the model directory has model.onnx (the cloud server ships only that), else torch."""
    if (Path(model_dir) / ONNX_FILE).exists():
        return OnnxClassifier(model_dir, max_length, max_chunks)
    return AiClassifier(model_dir, max_length, max_chunks)


class ClassifierHolder:
    """Keeps at most one AiClassifier, matching calibration/classifier.json. Used only from the
    single job worker (and the janitor's unload), so a plain lock is enough."""

    def __init__(self, repo_dir: Path, factory=None):
        self.repo_dir = Path(repo_dir)
        self._factory = factory or (lambda cfg: make_classifier(self.repo_dir / cfg["path"], int(cfg["max_length"]),
                                                                int(cfg["max_chunks"])))
        self._lock = threading.Lock()
        self._clf = None
        self._key = None
        self._failed_key = None  # don't retry a broken model on every check; a new config retries

    def get(self, cfg: dict | None):
        """The loaded classifier for this config, or None when there is no usable config or the
        model can't be loaded (the server then falls back to Binoculars verdicts)."""
        if not config_ok(cfg):
            return None
        key = (cfg["path"], cfg.get("version"))
        with self._lock:
            if self._clf is not None and self._key == key:
                return self._clf
            if self._failed_key == key:
                return None
            self._unload_locked()
            try:
                clf = self._factory(cfg)
                clf.load()
            except Exception:
                log.exception("could not load the classifier from %s", cfg.get("path"))
                self._failed_key = key
                return None
            self._clf, self._key = clf, key
            return clf

    def unload(self) -> None:
        with self._lock:
            self._unload_locked()

    def _unload_locked(self) -> None:
        if self._clf is not None:
            try:
                self._clf.unload()
            finally:
                self._clf, self._key = None, None
