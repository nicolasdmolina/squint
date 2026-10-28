# Squint for Mac

`Squint.app` is a Swift window (`Squint.swift`) around the normal Squint server, run by a
relocatable Python 3.12 bundled inside the app. Apple Silicon, macOS 14 or later. It is signed
ad-hoc, not by Apple, so people open it once with System Settings → Privacy & Security →
Open Anyway.

## Build

```sh
mac/build.sh                 # mac/build/Squint.app and mac/build/Squint-mac.zip
VERSION=0.2.0 mac/build.sh
```

Needs Xcode command line tools, `uv` with a managed Python 3.12 (`uv python install 3.12`),
Node for the web UI, and CMake for the first build. llama.cpp is compiled once with
`GGML_NATIVE=OFF` so the app runs on every M-series chip, then cached in `mac/build/wheels/`.
Delete that folder after changing the llama-cpp-python version.

## How it runs

1. The app starts `python3.12 -I -B -m squint.desktop --port N --resources Contents/Resources`
   and shows `http://127.0.0.1:N/`.
2. `squint.desktop` checks what's missing and serves a setup page first: the classifier on
   every Mac, plus the Falcon pair and tokenizer from Hugging Face on Macs with 16 GB or more.
   Downloads resume after a quit and are checked against their SHA-256.
3. Then it runs the server with `SQUINT_APP=1`: `full` mode with 16 GB or more, `preview`
   (classifier only) below that, no password, `[app]` limits.

| Where | What |
| --- | --- |
| `~/Library/Application Support/Squint/` | Models, `calibration/classifier.json`, `state.json`. Override with `SQUINT_APP_DATA`. |
| `~/Library/Logs/Squint/squint.log` | Server output. |

Quitting the app stops the server; if the app is killed, the server exits by itself.

## Shipping a new classifier

The app reads `mac/manifest.json` from `main` on GitHub at launch (falling back to the copy
in the app) and asks before downloading a newer classifier.

1. Promote it as usual so `calibration/classifier.json` has the new version.
2. Upload `squint-classifier-<version>.tar.gz` (the run folder, as one top-level directory) to
   a GitHub release `classifier-<version>`.
3. Update `mac/manifest.json`: `version`, `url`, `bytes`, `sha256`, and `config` (a copy of
   `classifier.json` with `path` set to `models/classifier/<run>`). `test_desktop.py` checks
   the manifest matches `classifier.json`.
4. Push to `main`. Apps pick it up on their next launch.

## Releasing the app

```sh
mac/build.sh
gh release create app-<version> mac/build/Squint-mac.zip --latest --title "Squint for Mac <version>"
```

The website links to `releases/latest/download/Squint-mac.zip`, so the app release must stay
marked latest (a later classifier release should be created with `--latest=false`).
