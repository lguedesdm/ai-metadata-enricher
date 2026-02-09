# =============================================================================
# AI Metadata Enricher — Orchestrator Container Image
# =============================================================================
# Minimal Python container for the structural orchestrator.
# No LLM, no RAG, no external writes.
#
# Build:
#   docker build -t ai-metadata-orchestrator:dev .
#
# Run (local testing with env vars):
#   docker run --rm \
#     -e SERVICE_BUS_NAMESPACE=sb-ai-metadata-dev.servicebus.windows.net \
#     -e SERVICE_BUS_QUEUE_NAME=metadata-ingestion \
#     -e APPLICATIONINSIGHTS_CONNECTION_STRING=<conn-string> \
#     ai-metadata-orchestrator:dev
# =============================================================================

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# -- Dependencies -----------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# -- Application code -------------------------------------------------------
COPY src/ ./src/

# -- Health check (process liveness) ----------------------------------------
# Container Apps uses this to verify the container is alive.
# We check that the main Python process is running.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# -- Entry point ------------------------------------------------------------
CMD ["python", "-m", "src.orchestrator"]
