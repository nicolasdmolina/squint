# The public preview server: the classifier only, from model.onnx, with no torch or llama.cpp.
#
#   tar -xzf squint-classifier-<version>-onnx.tar.gz -C server/models/classifier   # or squint.onnx_export
#   docker build -f ops/cloud/Dockerfile -t squint-cloud .
#   docker run -p 8017:8017 -e SQUINT_EDGE_SECRET=... squint-cloud
#
# The detector must be the promoted one (calibration/classifier.json); see ops/cloud/README.md.
FROM python:3.12-slim

RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30" "python-multipart>=0.0.9" "numpy>=1.26" \
    "tokenizers>=0.20" "python-docx>=1.1" "pypdf>=4.0" "onnxruntime>=1.20" \
 && useradd --create-home --uid 1000 squint

WORKDIR /srv/squint
COPY calibration/*.json calibration/
COPY server/pyproject.toml server/squint.toml server/
COPY server/src server/src
COPY server/models/classifier server/models/classifier
COPY ops/cloud/place_detector.py /tmp/
RUN python /tmp/place_detector.py && rm /tmp/place_detector.py

ENV PYTHONPATH=/srv/squint/server/src PYTHONUNBUFFERED=1 \
    SQUINT_MODE=preview SQUINT_HOST=0.0.0.0 SQUINT_PORT=8017 SQUINT_WEB_DIST=/nonexistent
USER squint
EXPOSE 8017
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8017/api/status', headers={'X-Squint-Edge': os.environ.get('SQUINT_EDGE_SECRET','')}), timeout=4)"
CMD ["python", "-c", "from squint.cli import server_main; server_main()"]
