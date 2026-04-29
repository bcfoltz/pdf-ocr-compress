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
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY .streamlit/ ./.streamlit/
COPY start_services.sh .
RUN chmod +x start_services.sh

# Expose Streamlit and API ports
EXPOSE 8501 8502

# Set environment variables
ENV STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_BROWSER_SERVER_ADDRESS=localhost

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

# Run both Streamlit GUI and FastAPI server
CMD ["bash", "-c", "streamlit run /app/src/pdf_ocr_compress/gui/basic.py & python -m uvicorn pdf_ocr_compress.api.server:app --host 0.0.0.0 --port 8502 & wait"]
