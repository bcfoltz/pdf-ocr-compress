# PDF OCR + Compression Tool - Docker Container
# Lightweight container with Python, Tesseract OCR, and Ghostscript

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps from pyproject.toml so the image picks up version
# floors maintained in one place. README.md is required because pyproject
# references it as `readme`.
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY .streamlit/ ./.streamlit/
COPY start_services.sh .
# Strip Windows CRLF line endings that break bash on Linux when the script
# is authored on Windows. sed is always available in python:*-slim.
RUN sed -i 's/\r//' start_services.sh && chmod +x start_services.sh

# Run as a non-root user (defense-in-depth). UID/GID 1000 matches the
# typical first-user UID on Linux distros so bind-mounted directories
# from the host (e.g. ./pdfs:/pdfs in docker-compose.yml) usually
# "just work". If your host UID isn't 1000, either:
#   - rebuild with `docker build --build-arg UID=$(id -u) ...`, or
#   - chown the bind-mounted directory on the host: `chown -R 1000:1000 ./pdfs`
# Docker Desktop on macOS / Windows handles UID mapping transparently.
ARG UID=1000
ARG GID=1000
RUN groupadd --system --gid ${GID} app \
    && useradd --system --uid ${UID} --gid ${GID} --create-home --shell /sbin/nologin app \
    && chown -R app:app /app
USER app

# Expose Streamlit and API ports
EXPOSE 8501 8502

# Set environment variables
ENV STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_BROWSER_SERVER_ADDRESS=localhost

# Health check — probes the API (the load-bearing surface). The Streamlit
# /_stcore/health endpoint reports green even when uvicorn has died,
# which is the wrong signal for an API-first backend service.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8502/health')"

# Run via start_services.sh — its SIGTERM/SIGINT trap is what makes
# `docker stop` shut down Streamlit and uvicorn cleanly. An inline
# CMD without that trap leaves the children orphaned on the kernel's
# 10-second SIGKILL timer.
CMD ["bash", "/app/start_services.sh"]
