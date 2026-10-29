"""Image build step: move the promoted detector's ONNX export (<run>-onnx) to the promoted path."""

import json
import sys
from pathlib import Path

cfg = json.loads(Path("calibration/classifier.json").read_text())
want = Path(cfg["path"])
onnx = want.with_name(want.name + "-onnx")
if not (onnx / "model.onnx").exists():
    sys.exit(f"missing {onnx}/model.onnx: unpack the {cfg['version']} ONNX detector there first")
for other in want.parent.iterdir():
    if other != onnx:
        sys.exit(f"unexpected {other}: only the promoted detector belongs in the image")
onnx.rename(want)
