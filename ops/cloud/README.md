# Cloud preview servers

The public site's checks run on cloud servers, not the Mac mini. Each one runs `Dockerfile` here:
the preview server with the classifier as ONNX (no torch, no Binoculars pair), about 800 MB of memory,
0.3–0.5 s a check after a 2–3 s cold start.

```
visitor ─▶ Worker (ops/edge) ─▶ pages: GitHub Pages (.github/workflows/site.yml)
                             └▶ /api: BACKENDS in order ─▶ Oracle A1 (primary)
                                                       └▶ Modal (standby, scales to zero)
                                  all down ─▶ 503 offline ─▶ the app shows example results
```

## Build the image

```sh
gh release download classifier-<version> -p '*-onnx.tar.gz' -D /tmp
tar -xzf /tmp/squint-classifier-<version>-onnx.tar.gz -C server/models/classifier
docker build -f ops/cloud/Dockerfile -t squint-cloud .
```

`<version>` is `calibration/classifier.json`'s. The build fails if the ONNX export is missing or a
second detector is in `server/models/classifier/`. Instead of downloading, you can export one
locally with `python -m squint.onnx_export` (see its docstring).

Run it with `SQUINT_EDGE_SECRET` set to the Worker's `EDGE_SECRET`: without it the server takes
`/api` calls from anyone and rate-limits by the caller's address.

## Oracle Cloud (primary)

Always Free A1 shape, 1 OCPU and 4 GB (Ubuntu, arm64). Oracle reclaims idle Always Free VMs
when CPU, network and memory all stay under 20% for 7 days; the server holds about 20% of 4 GB
with the model loaded, so keep `SQUINT_IDLE_UNLOAD_S` high (86400) to keep the model in memory.

```sh
docker run -d --restart unless-stopped --name squint -p 8017:8017 \
  -e SQUINT_EDGE_SECRET=... -e SQUINT_IDLE_UNLOAD_S=86400 squint-cloud
```

Put it behind a Cloudflare Tunnel (as `ops/cloudflared-squint.yml` does for the Mac mini) rather
than opening port 8017.

## Modal (standby)

Same image, `min_containers=0`, so it costs nothing while Oracle answers. Give it the same
`SQUINT_EDGE_SECRET` as a Modal secret and add its URL to the Worker's `BACKENDS` after Oracle's.

## Worker settings

- `BACKENDS`: comma-separated base URLs, tried in order (`origin` = the Mac mini tunnel).
- `EDGE_SECRET` (secret): the shared value above.

## A new detector

`classifier/promote.py`, then `classifier/publish.py` (uploads the release, rewrites
`mac/manifest.json`), then rebuild and redeploy each server with the new ONNX export.
