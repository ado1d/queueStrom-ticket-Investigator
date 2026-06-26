# syntax=docker/dockerfile:1.6
# ---------------------------------------------------------------------------
# QueueStorm Investigator — production image
# Multi-stage build: wheels are built in a fat builder, then copied into a
# slim runtime image. Target image size < 250 MB.
# ---------------------------------------------------------------------------

# ---- builder ---------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps for any wheels that need compilation (kept minimal).
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# Build wheels into /wheels so we don't need pip in the runtime image.
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# ---- runtime ---------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Run as a non-root user for safety.
RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /app app

WORKDIR /app

# Copy wheels and install them into the runtime image.
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Copy application code.
COPY app ./app

# Drop privileges.
USER app

# Expose the configured port (matches .env.example PORT=8000).
EXPOSE 8000

# Healthcheck hits the live endpoint; Render / Poridhi use the same path.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# Use exec form so signals (SIGTERM) are forwarded to uvicorn for graceful shutdown.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]