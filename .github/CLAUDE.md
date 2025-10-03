# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **cross-platform PDF OCR and compression tool**. It processes scanned PDFs using OCRmyPDF and Ghostscript.

## Architecture

Simple, working architecture:

```text
src/pdf_ocr_compress/
├── core/                    # Essential processing
│   ├── ocr.py              # OCR wrapper (OCRmyPDF)
│   ├── compress.py         # Compression (Ghostscript + pikepdf)
│   └── detect.py           # Text detection
├── gui/
│   └── basic.py            # Streamlit GUI (ONLY working GUI)
├── api/
│   └── server.py           # FastAPI REST API
├── config/
│   └── settings.py         # Basic configuration
└── utils/                   # Logging, errors, file utils
```

## Core Design Philosophy

- **Never overwrites originals**: All operations create new timestamped files
- **No in-place modifications**: Every function returns a new file path
- **Safety-first file handling**: Automatic collision avoidance with timestamps

## System Requirements

- **Python 3.9+** (required by latest ocrmypdf)
- **Cross-platform**: Windows 10/11, macOS 10.14+, Linux (Ubuntu 18.04+)
- **System Tools**: Tesseract OCR, Ghostscript
- **Conda Environment**: This project uses the conda environment named `pdf_ocr_compress`

## Common Commands

### Docker (Recommended)

```bash
# Start both GUI and API
docker-compose up

# Access services:
# - GUI: http://localhost:8501
# - API: http://localhost:8502
# - API Docs: http://localhost:8502/docs
```

### CLI Interface

```bash
# Smart auto-processing (recommended)
python -m pdf_ocr_compress process input.pdf output.pdf

# OCR with language detection
python -m pdf_ocr_compress ocr document.pdf output.pdf --lang eng

# Compression with quality preset
python -m pdf_ocr_compress compress large.pdf smaller.pdf --preset balanced

# Get help
python -m pdf_ocr_compress --help
```

### GUI Interface

```bash
# Streamlit GUI (THE ONLY GUI THAT WORKS)
streamlit run src/pdf_ocr_compress/gui/basic.py
```

### REST API

```bash
# Process a PDF via API
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@document.pdf" \
  -F "mode=auto" \
  -F "preset=balanced"

# View interactive API docs
open http://localhost:8502/docs
```

## Installation

### Docker (Recommended)

```bash
# Build and run
docker build -t pdf-ocr-compress .
docker run -p 8501:8501 pdf-ocr-compress

# Or with docker-compose
docker-compose up
```

### Local Installation

```bash
# With uv (recommended)
uv sync

# With pip
pip install -r requirements.txt
```

## Key Features

- OCR processing with OCRmyPDF
- PDF compression with multiple quality presets
- Text detection to determine if OCR is needed
- Streamlit web GUI
- Never overwrites original files

## Quality Presets

- **archival**: Minimal compression, preserves original quality
- **balanced**: High quality with moderate compression (default)
- **smallest**: Maximum compression for smallest file sizes

## File Naming Conventions

All operations create new timestamped files:

- `_ocr_{timestamp}.pdf`: OCR-only outputs
- `_processed_{timestamp}.pdf`: Auto-processed outputs
- `_compressed_{timestamp}.pdf`: Compression-only outputs

## Key Modules

### Core Processing

- `core/ocr.py`: OCR wrapper around OCRmyPDF
- `core/compress.py`: PDF compression using Ghostscript + pikepdf
- `core/detect.py`: Text detection heuristics using pdfminer

### GUI

- `gui/basic.py`: Simple Streamlit interface (THE ONLY GUI - DO NOT CREATE OTHERS)

### REST API

- `api/server.py`: FastAPI server for programmatic access
  - Endpoints: `/api/process`, `/api/download/{file_id}`, `/health`, `/docs`
  - Runs on port 8502 alongside Streamlit on 8501
  - Automatic file cleanup after 1 hour
  - Uses same core functions as GUI and CLI

## Important Notes for Claude Code

### When Working on This Project

1. **Keep it simple**: Don't add unnecessary features
2. **Don't create new GUIs**: basic.py is the only GUI
3. **Don't add "enterprise" features**: plugins, themes, smart analysis, etc. - NONE OF THIS
4. **Test changes**: Make sure basic.py still works after changes
5. **Cross-platform**: Windows, macOS, and Linux

### Common Patterns

- **Configuration**: Use `config/settings.py` for basic settings
- **Logging**: Use `utils/get_logger(__name__)` for consistent logging
- **File safety**: Always create new files, never overwrite originals
- **Error handling**: Provide user-friendly error messages with actionable advice

### What NOT to do

- DO NOT create `simple_first.py` or any other GUI files
- DO NOT add themes, drag-drop, setup wizards, or UI components
- DO NOT add plugins, enterprise features, or performance modules
- DO NOT add smart analysis, caching, or user experience tracking
- KEEP IT SIMPLE

## Docker Deployment

The project includes Docker support for easy deployment without installing system dependencies.

### Quick Start

```bash
# Using docker-compose (recommended)
docker-compose up

# Or manually with docker
docker build -t pdf-ocr-compress .
docker run -p 8501:8501 pdf-ocr-compress
```

Access the app at <http://localhost:8501>

### Docker Files

- `Dockerfile` - Container definition with Python 3.11, Tesseract, and Ghostscript
- `.dockerignore` - Excludes unnecessary files from Docker build
- `docker-compose.yml` - Simple orchestration with volume mounts and resource limits

### Container Specifications

- **Base image**: `python:3.11-slim` (~800MB total image size)
- **System dependencies**: Tesseract OCR (English only), Ghostscript
- **Python packages**: ocrmypdf, pikepdf, pdfminer.six, streamlit, typer, rich
- **Port**: 8501 (Streamlit default)
- **Health check**: Streamlit's `/_stcore/health` endpoint
- **Resource limits**: 2GB RAM max, 2 CPUs max (configurable in docker-compose.yml)

### Volume Mounts

The docker-compose.yml includes `./pdfs:/pdfs` volume mount for local file processing. Create a `pdfs/` directory to share files with the container.

### Docker Environment Variables

Configured in Dockerfile and docker-compose.yml:

- `STREAMLIT_SERVER_PORT=8501` - Port for web interface
- `STREAMLIT_SERVER_ADDRESS=0.0.0.0` - Listen on all interfaces
- `STREAMLIT_BROWSER_SERVER_ADDRESS=localhost` - Display correct URL to users
- `STREAMLIT_SERVER_MAX_UPLOAD_SIZE=4096` - Max upload 4GB
- `STREAMLIT_SERVER_HEADLESS=true` - Run without browser
- `STREAMLIT_BROWSER_GATHER_USAGE_STATS=false` - Disable telemetry

### Deployment Platforms

Successfully tested on:

- **Local**: Docker Desktop (Windows, macOS), Docker Engine (Linux)
- **NAS**: Synology DSM, Unraid, TrueNAS SCALE
- **Cloud**: AWS ECS, Google Cloud Run, Azure Container Instances

### Adding Language Support

To add more Tesseract languages, edit the Dockerfile:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-spa \
    tesseract-ocr-fra \
    tesseract-ocr-deu \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*
```

Then rebuild: `docker-compose up --build`

## Markdown Best Practices

When writing or updating markdown files in this project, follow these rules:

### Formatting Rules

1. **Blank lines after headings**: Always include a blank line after every heading
2. **Blank lines after code fences**: Always include a blank line after closing code fences (```)
3. **Blank lines before/after lists**: Include blank lines before and after list blocks
4. **No emphasis in headings**: Never use bold (**) or italic (*) in headings - the heading itself provides emphasis
5. **No bare URLs**: Wrap URLs in angle brackets: `<http://example.com>` instead of `http://example.com`
6. **Specify code block languages**: Always specify the language for code blocks: ` ```bash ` not just ` ``` `

### Common Language Identifiers

- `bash` - Shell commands
- `python` - Python code
- `powershell` - PowerShell commands
- `text` - Plain text, directory trees, or output
- `json` - JSON data
- `yaml` - YAML configuration

### Example

Good:

```markdown
## Installation

Follow these steps:

```bash
pip install -r requirements.txt
```

Visit <http://localhost:8501> to view the app.
```

Bad:

```markdown
## **Installation**
Follow these steps:
```
pip install -r requirements.txt
```
Visit http://localhost:8501 to view the app.
```
