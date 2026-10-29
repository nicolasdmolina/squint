"""The public preview server on Modal: scales to zero, wakes on the first /api call.

  uvx modal secret create squint-edge SQUINT_EDGE_SECRET=<the Worker's EDGE_SECRET>
  uvx modal deploy ops/cloud/modal_app.py

The image downloads the promoted detector's ONNX export from its GitHub release (classifier/publish.py),
so publish before deploying. See ops/cloud/README.md.
"""

from pathlib import Path

import modal

SRV = "/srv/squint"
PACKAGES = ["fastapi>=0.115", "uvicorn>=0.30", "python-multipart>=0.0.9", "numpy>=1.26", "tokenizers>=0.20",
            "python-docx>=1.1", "pypdf>=4.0", "onnxruntime>=1.20"]
FETCH_DETECTOR = """
import io, json, pathlib, tarfile, urllib.request
cfg = json.loads(pathlib.Path("calibration/classifier.json").read_text())
want = pathlib.Path(cfg["path"])
v = cfg["version"]
url = f"https://github.com/nicolasdmolina/squint/releases/download/classifier-{v}/squint-classifier-{v}-onnx.tar.gz"
want.parent.mkdir(parents=True)
with urllib.request.urlopen(url) as r, tarfile.open(fileobj=io.BytesIO(r.read())) as tar:
    tar.extractall(want.parent, filter="data")
want.with_name(want.name + "-onnx").rename(want)
assert (want / "model.onnx").exists()
"""

# add_local_* do nothing inside the container, where this file sits at /root and has no repo beside it
REPO = Path(__file__).resolve().parents[2] if modal.is_local() else Path("/")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(*PACKAGES)
    .env({"PYTHONPATH": f"{SRV}/server/src", "SQUINT_MODE": "preview", "SQUINT_WEB_DIST": "/nonexistent"})
    .add_local_file(REPO / "calibration" / "classifier.json", f"{SRV}/calibration/classifier.json", copy=True)
    .run_commands(f"cd {SRV} && python -c '{FETCH_DETECTOR}'")
    .add_local_file(REPO / "calibration" / "thresholds.json", f"{SRV}/calibration/thresholds.json")
    .add_local_file(REPO / "calibration" / "report.json", f"{SRV}/calibration/report.json")
    .add_local_file(REPO / "server" / "squint.toml", f"{SRV}/server/squint.toml")
    .add_local_dir(REPO / "server" / "src", f"{SRV}/server/src", ignore=["**/__pycache__"])
)

app = modal.App("squint", image=image)


@app.function(secrets=[modal.Secret.from_name("squint-edge")], cpu=1.0, memory=2048,
              scaledown_window=300, max_containers=1, timeout=120)
@modal.concurrent(max_inputs=32)
@modal.asgi_app()
def web():
    # one container holds the queue and the rate limits, like the Mac mini server
    from squint.app import create_app
    from squint.config import load_settings

    return create_app(load_settings())
