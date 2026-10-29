"""Export a promoted classifier to ONNX for the cloud preview server (clf.OnnxClassifier).

    python -m squint.onnx_export server/models/classifier/<run> [--out DIR]

Writes model.onnx (fp32: int8 changed verdicts at the sharp cutoff) plus the tokenizer and config
into DIR (default: <run>-onnx), then checks the ONNX model against torch on a few texts and fails
if any window's logits differ by more than 1e-3 or the token ids differ. Needs torch, transformers,
onnx and onnxruntime: `uv run --with onnx --with onnxruntime python -m squint.onnx_export ...`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .clf import ONNX_FILE, AiClassifier, OnnxClassifier

COPY = ("config.json", "tokenizer.json", "tokenizer_config.json", "trained.json")
TOLERANCE = 1e-3
PROBES = [
    "The mitochondria is the powerhouse of the cell, and this essay explains why that phrase stuck.",
    "lol ok so i finally tried the new ramen place downtown and honestly?? mid. broth was fine tho",
    "In conclusion, it is important to note that technology offers both opportunities and challenges. " * 60,
]


def export(src: Path, out: Path) -> None:
    import torch
    from transformers import AutoModelForSequenceClassification

    out.mkdir(parents=True, exist_ok=True)
    # eager attention: the sdpa and compiled paths don't export cleanly
    model = AutoModelForSequenceClassification.from_pretrained(str(src), attn_implementation="eager").eval()
    if hasattr(model.config, "reference_compile"):
        model.config.reference_compile = False
    ids = torch.randint(5, 1000, (1, 64))
    torch.onnx.export(model, (ids, torch.ones_like(ids)), str(out / ONNX_FILE),
                      input_names=["input_ids", "attention_mask"], output_names=["logits"],
                      dynamic_axes={"input_ids": {0: "batch", 1: "tokens"},
                                    "attention_mask": {0: "batch", 1: "tokens"}, "logits": {0: "batch"}},
                      opset_version=17, dynamo=False)
    for name in COPY:
        if (src / name).exists():
            shutil.copyfile(src / name, out / name)


def check(src: Path, out: Path) -> float:
    """Largest P(AI) difference over PROBES; raises if the two disagree beyond TOLERANCE."""
    ref = AiClassifier(src, 512, 8)
    ref.load()
    got = OnnxClassifier(out, 512, 8)
    got.load()
    for text in PROBES:
        a = ref._tok(text, add_special_tokens=False)["input_ids"]
        b = got._tok.encode(text, add_special_tokens=False).ids
        if a != b:
            raise SystemExit(f"onnx_export: tokenizers disagree on {text[:40]!r}")
    if ref._template != got._template:
        raise SystemExit("onnx_export: special-token templates disagree")
    worst = max(abs(x - y) for x, y in zip(ref.predict(PROBES), got.predict(PROBES)))
    if worst > TOLERANCE:
        raise SystemExit(f"onnx_export: ONNX and torch differ by {worst:.2e}")
    return worst


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m squint.onnx_export", description=__doc__.splitlines()[0])
    ap.add_argument("model_dir", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    src = args.model_dir.resolve()
    out = (args.out or src.with_name(src.name + "-onnx")).resolve()
    if not (src / "model.safetensors").exists():
        sys.exit(f"onnx_export: no model.safetensors in {src}")
    export(src, out)
    worst = check(src, out)
    print(f"{out / ONNX_FILE}: {(out / ONNX_FILE).stat().st_size / 1e6:.0f} MB, max P(AI) difference {worst:.1e}")


if __name__ == "__main__":
    main()
