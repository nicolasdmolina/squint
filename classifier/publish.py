"""Publish the promoted classifier: a GitHub release the Mac app and cloud servers download from.

  python3 classifier/publish.py [--dry-run]

Run after promote.py. Reads calibration/classifier.json, packs server/models/classifier/<run>/
(plus MODEL_LICENSE.md) as squint-classifier-<version>.tar.gz, and, when <run>-onnx/ exists, the
ONNX export as squint-classifier-<version>-onnx.tar.gz. Uploads both to the release
classifier-<version> (never marked latest: that stays the app release) and rewrites
mac/manifest.json to point at it. Needs the gh CLI, logged in. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GITHUB = "nicolasdmolina/squint"
PROMOTED = REPO / "calibration" / "classifier.json"
MANIFEST = REPO / "mac" / "manifest.json"
LICENSE = REPO / "MODEL_LICENSE.md"


def pack(run_dir: Path, out: Path) -> tuple[int, str]:
    with tarfile.open(out, "w:gz") as tar:
        for f in sorted(run_dir.iterdir()):
            tar.add(f, arcname=f"{run_dir.name}/{f.name}")
        tar.add(LICENSE, arcname=f"{run_dir.name}/{LICENSE.name}")
    digest = hashlib.sha256()
    with out.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return out.stat().st_size, digest.hexdigest()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="publish.py", description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="pack and print, upload nothing")
    args = ap.parse_args(argv)

    cfg = json.loads(PROMOTED.read_text())
    version, run_dir = cfg["version"], REPO / cfg["path"]
    if not (run_dir / "model.safetensors").exists():
        sys.exit(f"publish: no model.safetensors in {run_dir}")
    tag, name = f"classifier-{version}", f"squint-classifier-{version}.tar.gz"

    with tempfile.TemporaryDirectory() as tmp:
        assets = [Path(tmp) / name]
        size, sha = pack(run_dir, assets[0])
        onnx_dir = run_dir.with_name(run_dir.name + "-onnx")
        if onnx_dir.is_dir():
            assets.append(Path(tmp) / f"squint-classifier-{version}-onnx.tar.gz")
            pack(onnx_dir, assets[-1])
        for a in assets:
            print(f"{a.name}: {a.stat().st_size / 1e6:.0f} MB")
        if args.dry_run:
            return
        notes = (f"Detector {version} ({cfg['run']}). Squint for Mac offers it as an update. "
                 "Weights: CC BY-NC-SA 4.0, see MODEL_LICENSE.md.")
        subprocess.run(["gh", "release", "create", tag, "--repo", GITHUB, "--latest=false",
                        "--title", f"Detector {version}", "--notes", notes, *map(str, assets)], check=True)

    # the app installs under its own data dir, so the path is relative to it, not the repo
    config = {**cfg, "path": f"models/classifier/{run_dir.name}"}
    manifest = {"classifier": {
        "version": version,
        "url": f"https://github.com/{GITHUB}/releases/download/{tag}/{name}",
        "bytes": size, "sha256": sha, "config": config,
    }}
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{MANIFEST.relative_to(REPO)}: {version}")


if __name__ == "__main__":
    main()
