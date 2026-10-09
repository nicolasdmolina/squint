"""How long texts become model inputs (pure Python, shared by training and inference).

A text is tokenised once, then cut into consecutive windows of `body_len` tokens (the model's
max length minus its special tokens). A short tail window is replaced by the last full-size
window so no chunk is a few stray tokens. Training keeps at most `max_chunks` evenly spaced
windows per text, so a 2,000-word essay does not outweigh fifty short reviews. Inference
averages the chunk probabilities, weighted by chunk length.
"""

from __future__ import annotations


def chunk_token_ids(ids: list[int], body_len: int, max_chunks: int | None = None) -> list[list[int]]:
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
