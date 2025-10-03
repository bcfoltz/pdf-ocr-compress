# API Examples - Ready to Use

Complete curl command examples for the PDF OCR + Compression REST API. These can be imported into n8n, Postman, Insomnia, or used directly in the terminal.

## Quick Reference

- **Base URL**: `http://localhost:8502`
- **API Documentation**: <http://localhost:8502/docs>
- **Health Check**: <http://localhost:8502/health>

## Basic Usage

### 1. Process PDF with Default Settings (Auto Mode)

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@/path/to/your/document.pdf" \
  -F "mode=auto" \
  -F "preset=balanced"
```

### 2. Download Processed File

```bash
# Use the file_id from the response above
curl -X GET "http://localhost:8502/api/download/YOUR_FILE_ID_HERE" \
  -o processed_output.pdf
```

### 3. Complete Workflow (Process + Download)

```bash
# Step 1: Process and capture response
RESPONSE=$(curl -X POST "http://localhost:8502/api/process" \
  -F "file=@document.pdf" \
  -F "mode=auto" \
  -F "preset=balanced")

# Step 2: Extract file_id from response
FILE_ID=$(echo $RESPONSE | grep -o '"file_id":"[^"]*"' | cut -d'"' -f4)

# Step 3: Download processed file
curl -X GET "http://localhost:8502/api/download/$FILE_ID" \
  -o processed_output.pdf
```

## Processing Modes

### OCR Only Mode

Add searchable text to scanned PDFs without compression:

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@scanned_document.pdf" \
  -F "mode=ocr" \
  -F "preset=balanced" \
  -F "language=eng"
```

### Compress Only Mode

Reduce file size without adding OCR:

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@large_document.pdf" \
  -F "mode=compress" \
  -F "preset=smallest"
```

### Auto Mode (Recommended)

Automatically detects if OCR is needed, then compresses:

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@document.pdf" \
  -F "mode=auto" \
  -F "preset=balanced"
```

## Quality Presets

### Archival Quality (Minimal Compression)

Best for legal documents, archival purposes:

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@important_contract.pdf" \
  -F "mode=auto" \
  -F "preset=archival"
```

### Balanced Quality (Default)

Good balance between quality and file size:

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@document.pdf" \
  -F "mode=auto" \
  -F "preset=balanced"
```

### Smallest File Size

Maximum compression for email/web:

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@document.pdf" \
  -F "mode=auto" \
  -F "preset=smallest"
```

## Advanced Options

### Multiple Languages OCR

For documents with multiple languages:

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@multilingual_document.pdf" \
  -F "mode=ocr" \
  -F "language=eng+spa+fra" \
  -F "preset=balanced"
```

### Force OCR (Even if Text Exists)

Re-OCR documents that already have text:

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@document.pdf" \
  -F "mode=auto" \
  -F "force_ocr=true" \
  -F "language=eng"
```

### PDF/A Compliance

Create PDF/A-2 compliant archives:

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@document.pdf" \
  -F "mode=ocr" \
  -F "pdfa=true" \
  -F "preset=archival"
```

### Parallel Processing (Faster OCR)

Use more CPU cores for faster processing:

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@large_document.pdf" \
  -F "mode=ocr" \
  -F "jobs=8" \
  -F "language=eng"
```

### All Options Combined

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@document.pdf" \
  -F "mode=auto" \
  -F "preset=balanced" \
  -F "language=eng+spa" \
  -F "pdfa=true" \
  -F "force_ocr=false" \
  -F "jobs=4"
```

## Response Examples

### Success Response

```json
{
  "status": "success",
  "message": "Processing complete",
  "file_id": "abc123-def456-ghi789",
  "mode": "auto",
  "preset": "balanced",
  "original_size": 5242880,
  "output_size": 2621440,
  "reduction_percent": 50.0,
  "processing_time": 15.3
}
```

### Error Response

```json
{
  "status": "error",
  "error": "Invalid mode: invalid_mode"
}
```

## Parameter Reference

| Parameter | Type | Required | Default | Options | Description |
|-----------|------|----------|---------|---------|-------------|
| `file` | file | ✅ Yes | - | PDF file | PDF file to process |
| `mode` | string | No | `auto` | `auto`, `ocr`, `compress` | Processing mode |
| `preset` | string | No | `balanced` | `archival`, `balanced`, `smallest` | Quality preset |
| `language` | string | No | `eng` | Tesseract codes | OCR language(s), use `+` to combine |
| `pdfa` | boolean | No | `false` | `true`, `false` | Produce PDF/A-2 output |
| `force_ocr` | boolean | No | `false` | `true`, `false` | Force OCR even if text exists |
| `jobs` | integer | No | `4` | `1-32` | Parallel jobs for OCR |

## Language Codes (Common)

| Code | Language | Code | Language |
|------|----------|------|----------|
| `eng` | English | `spa` | Spanish |
| `fra` | French | `deu` | German |
| `ita` | Italian | `por` | Portuguese |
| `rus` | Russian | `chi_sim` | Chinese (Simplified) |
| `chi_tra` | Chinese (Traditional) | `jpn` | Japanese |
| `kor` | Korean | `ara` | Arabic |

Full list: <https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html>

## n8n Integration

### Method 1: HTTP Request Node (Process)

1. Add **HTTP Request** node
2. Configure:
   - **Method**: `POST`
   - **URL**: `http://localhost:8502/api/process`
   - **Body Content Type**: `Multipart-Form Data`
   - **Specify Body**: `Using Fields Below`
3. Add parameters:
   - Name: `file`, Value: `{{ $binary.data }}`
   - Name: `mode`, Value: `auto`
   - Name: `preset`, Value: `balanced`
4. **Response Format**: `JSON`

### Method 2: HTTP Request Node (Download)

1. Add **HTTP Request** node
2. Configure:
   - **Method**: `GET`
   - **URL**: `http://localhost:8502/api/download/{{ $json.file_id }}`
   - **Response Format**: `File`
   - **Binary Property**: `data`

### Complete n8n Workflow

```text
[Trigger] → [HTTP Request: Process] → [HTTP Request: Download] → [Output]
```

Example n8n code block (import this):

```json
{
  "nodes": [
    {
      "parameters": {
        "requestMethod": "POST",
        "url": "http://localhost:8502/api/process",
        "options": {
          "bodyContentType": "multipart-form-data"
        },
        "bodyParametersUi": {
          "parameter": [
            {
              "name": "file",
              "value": "={{ $binary.data }}"
            },
            {
              "name": "mode",
              "value": "auto"
            },
            {
              "name": "preset",
              "value": "balanced"
            }
          ]
        }
      },
      "name": "Process PDF",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 1,
      "position": [400, 300]
    },
    {
      "parameters": {
        "url": "=http://localhost:8502/api/download/{{ $json.file_id }}",
        "options": {
          "response": {
            "response": {
              "responseFormat": "file"
            }
          }
        }
      },
      "name": "Download Processed PDF",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 1,
      "position": [600, 300]
    }
  ],
  "connections": {
    "Process PDF": {
      "main": [
        [
          {
            "node": "Download Processed PDF",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  }
}
```

## Python Integration

### Simple Example

```python
import requests

# Process PDF
with open("document.pdf", "rb") as f:
    response = requests.post(
        "http://localhost:8502/api/process",
        files={"file": f},
        data={
            "mode": "auto",
            "preset": "balanced",
            "language": "eng"
        }
    )

result = response.json()
print(f"Processing complete: {result['reduction_percent']}% reduction")

# Download processed file
file_id = result["file_id"]
download = requests.get(f"http://localhost:8502/api/download/{file_id}")

with open("processed.pdf", "wb") as f:
    f.write(download.content)
```

### Advanced Example with Error Handling

```python
import requests
import sys

def process_pdf(input_path, output_path, mode="auto", preset="balanced"):
    """Process a PDF file via API."""
    try:
        # Upload and process
        with open(input_path, "rb") as f:
            response = requests.post(
                "http://localhost:8502/api/process",
                files={"file": f},
                data={
                    "mode": mode,
                    "preset": preset,
                    "language": "eng",
                    "jobs": 4
                },
                timeout=600  # 10 minute timeout for large files
            )

        response.raise_for_status()
        result = response.json()

        if result["status"] != "success":
            print(f"Error: {result.get('error', 'Unknown error')}")
            return False

        # Download processed file
        file_id = result["file_id"]
        download = requests.get(
            f"http://localhost:8502/api/download/{file_id}",
            timeout=300
        )
        download.raise_for_status()

        # Save to disk
        with open(output_path, "wb") as f:
            f.write(download.content)

        # Print stats
        original_mb = result["original_size"] / 1024 / 1024
        output_mb = result["output_size"] / 1024 / 1024
        print(f"✓ Success!")
        print(f"  Original: {original_mb:.1f} MB")
        print(f"  Output: {output_mb:.1f} MB")
        print(f"  Reduction: {result['reduction_percent']:.1f}%")
        print(f"  Time: {result['processing_time']:.1f}s")

        return True

    except requests.exceptions.Timeout:
        print("Error: Request timed out")
        return False
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python script.py input.pdf output.pdf")
        sys.exit(1)

    success = process_pdf(sys.argv[1], sys.argv[2])
    sys.exit(0 if success else 1)
```

## Testing the API

### Health Check

```bash
curl http://localhost:8502/health
```

Expected response:

```json
{
  "status": "healthy",
  "service": "pdf-ocr-compress-api"
}
```

### API Root

```bash
curl http://localhost:8502/
```

### Interactive Documentation

Open in browser: <http://localhost:8502/docs>

This provides:

- Interactive API testing
- Full schema documentation
- Example requests and responses
- Try-it-out functionality

## Troubleshooting

### Connection Refused

```bash
# Check if Docker container is running
docker ps

# Check logs
docker logs pdf-ocr-compress

# Restart container
docker-compose restart
```

### File Not Found Error

```bash
# Verify file path is correct
ls -la /path/to/file.pdf

# Use absolute path
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@/absolute/path/to/document.pdf" \
  -F "mode=auto"
```

### Timeout on Large Files

```bash
# Increase curl timeout (in seconds)
curl --max-time 600 -X POST "http://localhost:8502/api/process" \
  -F "file=@large_document.pdf" \
  -F "mode=auto"
```

### File ID Expired

Files are automatically deleted after 1 hour. Download immediately after processing or increase retention in `api/server.py`.

## Performance Tips

1. **Use `compress` mode only** if your PDFs already have searchable text
2. **Adjust `jobs` parameter** based on CPU cores (check with `nproc` on Linux)
3. **Use `smallest` preset** for web publishing or email attachments
4. **Use `archival` preset** for legal documents or long-term storage
5. **Process files locally** in Docker for best performance (avoid network uploads)

## Security Notes

- This API has **no authentication** by default - use firewall rules or reverse proxy with auth
- Files are stored temporarily and deleted after 1 hour
- Consider rate limiting for production use
- For production, use HTTPS and proper authentication
