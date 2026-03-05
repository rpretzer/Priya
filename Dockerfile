# syntax=docker/dockerfile:1
# Multi-stage build — keeps the runtime image lean.
#
# Build:
#   docker build -t hoopla-coach .
#
# Run (with Ollama on the host or in compose):
#   docker run --rm -p 3456:3456 \
#     -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
#     -v hoopla-data:/data \
#     hoopla-coach
#
# Run with Bedrock:
#   docker run --rm -p 3456:3456 \
#     -e BACKEND=bedrock -e AWS_REGION=us-east-1 \
#     -v ~/.aws:/root/.aws:ro \
#     -v hoopla-data:/data \
#     hoopla-coach

# ------- builder stage -------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Copy dependency manifest and install into a prefix we can copy to runtime
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt


# ------- runtime stage -------------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Hoopla Coach (Priya)"
LABEL org.opencontainers.image.description="Spec-funnel coaching server for Hoopla Digital product teams"

# Non-root user for security
RUN groupadd -r coach && useradd -r -g coach -d /app coach

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY pipeline/ ./pipeline/

# Data directory — memory DB lives here (mount a volume in production)
RUN mkdir -p /data && chown coach:coach /data

USER coach

# Environment defaults (override via -e or docker-compose env_file)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MEMORY_PATH=/data/memory.db \
    PORT=3456 \
    BACKEND=ollama \
    WORKERS=1

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health', timeout=4)"

CMD ["sh", "-c", \
     "python3 -m pipeline.coach \
      --port ${PORT} \
      --backend ${BACKEND} \
      --memory-path ${MEMORY_PATH} \
      --workers ${WORKERS}"]
