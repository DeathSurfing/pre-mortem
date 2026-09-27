FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl is needed for the container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Assert the runtime deps exist AT BUILD TIME. A Dokploy stack never builds this image in CI, so a
# missing runtime dependency would otherwise pass CI green and only fail at deploy.
RUN pip install -r requirements.txt \
    && python -c "import fastapi, uvicorn, httpx, hindsight_client, hindsight_client_api; print('deps ok')"

COPY app ./app
COPY tests ./tests

# bind 0.0.0.0 or Traefik cannot reach the container
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
