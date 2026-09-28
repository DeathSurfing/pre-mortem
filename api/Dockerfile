FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models/hf \
    LAYA_REPO=techtheist/laya-onnx \
    LAYA_SUBFOLDER=en \
    LAYA_ONNX_FILE=model_int4.onnx

# curl for the healthcheck. libgomp1 is required by torch's CPU kernels; without it the import fails at
# runtime with "libgomp.so.1: cannot open shared object file", which only shows up on the first request.
RUN apt-get update && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Assert the runtime deps at BUILD time. A Dokploy stack never builds this image in CI, so a missing
# runtime dependency would otherwise pass CI green and only fail at deploy.
RUN pip install -r requirements.txt \
    && python -c "import fastapi, uvicorn, httpx, hindsight_client, hindsight_client_api; print('core deps ok')" \
    && python -c "import torch, onnxruntime, transformers; print('torch', torch.__version__, '| ort', onnxruntime.__version__)" \
    && python -c "import psycopg; print('psycopg', psycopg.__version__)" \
    && python -c "from laya.onnx_agent import ONNXAgent; print('laya import ok')"

# Bake the Laya weights into the image and record the exact snapshot path. Without this the first request
# pays a ~275MB download, and the container needs hub access at runtime.
RUN python -c "\
from huggingface_hub import snapshot_download; \
p = snapshot_download('techtheist/laya-onnx', allow_patterns=['en/*']); \
open('/models/laya_path', 'w').write(p); \
print('laya snapshot at', p)" \
    && cat /models/laya_path \
    && ls -la "$(cat /models/laya_path)/en/"

COPY app ./app
COPY tests ./tests
COPY scripts ./scripts

# Point the app at the baked snapshot so no hub call happens at boot. Also warm the prompt-store embedder
# at BUILD time: bge-small is a separate download from Laya, and without this the first prompt of a fresh
# deploy eats a cold model fetch at request time.
RUN printf '#!/bin/sh\nexport LAYA_LOCAL_DIR="$(cat /models/laya_path)"\nexec "$@"\n' > /entrypoint.sh \
    && chmod +x /entrypoint.sh \
    && python -c "\
from transformers import AutoModel, AutoTokenizer; \
AutoTokenizer.from_pretrained('BAAI/bge-small-en-v1.5'); \
AutoModel.from_pretrained('BAAI/bge-small-en-v1.5'); \
print('embedder cached')"

EXPOSE 8000
# 0.0.0.0 or Traefik cannot reach the container. One worker: the ONNX session is per-process and the int4
# model peaks at ~996MB, so extra workers would multiply memory for no throughput gain (1.4-3s per call).
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
