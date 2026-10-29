# Cloud preview servers

The public site's checks run on Modal, with the Mac mini as backup. The cloud server is the preview
server with the classifier as ONNX (no torch, no Binoculars pair): about 800 MB of memory, 0.3–0.5 s a
check once the model is loaded.

```
visitor ─▶ Worker (ops/edge) ─▶ pages: GitHub Pages (.github/workflows/site.yml)
                             └▶ /api: BACKENDS in order ─▶ Modal (scales to zero)
                                                       └▶ origin: the Mac mini tunnel
                                  all down ─▶ 503 offline ─▶ the app shows example results
```

## Modal

```sh
uvx modal secret create squint-edge SQUINT_EDGE_SECRET=<the Worker's EDGE_SECRET>
uvx modal deploy ops/cloud/modal_app.py
```

The image downloads the promoted detector's ONNX export from its GitHub release, so run
`classifier/publish.py` first. It scales to zero after 5 idle minutes; the web UI's first
`/api/status` call wakes it while the visitor is still typing. At a few visits a month this stays
far inside Modal's free monthly credit.

## Any other host

`Dockerfile` builds the same server for a VM:

```sh
gh release download classifier-<version> -p '*-onnx.tar.gz' -D /tmp
tar -xzf /tmp/squint-classifier-<version>-onnx.tar.gz -C server/models/classifier
docker build -f ops/cloud/Dockerfile -t squint-cloud .
docker run -d --restart unless-stopped -p 8017:8017 -e SQUINT_EDGE_SECRET=... squint-cloud
```

Without `SQUINT_EDGE_SECRET` the server takes `/api` calls from anyone and rate-limits by the
caller's address.

## Worker settings

- `BACKENDS`: comma-separated base URLs, tried in order (`origin` = the Mac mini tunnel).
- `EDGE_SECRET` (secret): the shared value above.

## A new detector

`classifier/promote.py`, then `classifier/publish.py` (uploads the release, rewrites
`mac/manifest.json`), then `modal deploy` again.
