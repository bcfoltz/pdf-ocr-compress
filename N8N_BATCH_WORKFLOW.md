# n8n Batch Processing Workflows

Complete n8n workflow examples for batch processing PDFs from local folders, Google Drive, Dropbox, and other sources.

## Overview

The API is fully compatible with n8n binary data. Your workflow will:

1. **List files** from source (local folder, Google Drive, etc.)
2. **Download/Read files** as n8n binary data
3. **Process each PDF** via API (automatically handles n8n binary format)
4. **Save results** back to destination

### Important: Filename Behavior

- **Download endpoint returns original filename unchanged** - The API preserves your original PDF filename
- **All processing metadata is in the JSON response** - mode, preset, file sizes, reduction %, and processing time are returned for later use
- **Filename customization is optional** - You can use the "Set: Build Filename" node if you want to add metadata to filenames, but it's not required

## Workflow 1: Local Folder Batch Processing

Process all PDFs in a local folder automatically.

### Nodes Setup

```text
[Schedule Trigger] → [Read Binary Files] → [Loop Over Items] → [HTTP Request: Process] → [HTTP Request: Download] → [Write Binary File]
```

### Complete n8n JSON (Import This)

```json
{
  "name": "PDF OCR Batch - Local Folder",
  "nodes": [
    {
      "parameters": {
        "rule": {
          "interval": [
            {
              "field": "cronExpression",
              "expression": "0 */6 * * *"
            }
          ]
        }
      },
      "name": "Every 6 Hours",
      "type": "n8n-nodes-base.scheduleTrigger",
      "typeVersion": 1,
      "position": [240, 300]
    },
    {
      "parameters": {
        "filePath": "/path/to/pdfs/*.pdf",
        "options": {}
      },
      "name": "Read PDF Files",
      "type": "n8n-nodes-base.readBinaryFiles",
      "typeVersion": 1,
      "position": [440, 300]
    },
    {
      "parameters": {
        "batchSize": 1,
        "options": {}
      },
      "name": "Loop Over Files",
      "type": "n8n-nodes-base.splitInBatches",
      "typeVersion": 1,
      "position": [640, 300]
    },
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
            },
            {
              "name": "language",
              "value": "eng"
            },
            {
              "name": "jobs",
              "value": "4"
            }
          ]
        }
      },
      "name": "Process PDF",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 3,
      "position": [840, 300]
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
      "name": "Download Processed",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 3,
      "position": [1040, 300]
    },
    {
      "parameters": {
        "fileName": "={{ $json.fileName.replace('.pdf', '_processed.pdf') }}",
        "dataPropertyName": "data",
        "options": {
          "folderPath": "/path/to/output/"
        }
      },
      "name": "Save Processed PDF",
      "type": "n8n-nodes-base.writeBinaryFile",
      "typeVersion": 1,
      "position": [1240, 300]
    }
  ],
  "connections": {
    "Every 6 Hours": {
      "main": [
        [
          {
            "node": "Read PDF Files",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Read PDF Files": {
      "main": [
        [
          {
            "node": "Loop Over Files",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Loop Over Files": {
      "main": [
        [
          {
            "node": "Process PDF",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Process PDF": {
      "main": [
        [
          {
            "node": "Download Processed",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Download Processed": {
      "main": [
        [
          {
            "node": "Save Processed PDF",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  }
}
```

## Workflow 2: Google Drive Batch Processing

Process PDFs from a Google Drive folder and save results back to Drive.

### Prerequisites

1. Set up Google Drive credentials in n8n
2. Create a folder for processed PDFs in Google Drive

### Nodes Setup

**Simple Workflow (Recommended):**

```text
[Schedule Trigger] → [Google Drive: List Files] → [Loop Over Items] → [Google Drive: Download] → [HTTP Request: Process] → [HTTP Request: Download] → [Google Drive: Upload]
```

**Advanced Workflow (With Custom Filenames):**

```text
[Schedule Trigger] → [Google Drive: List Files] → [Loop Over Items] → [Google Drive: Download] → [HTTP Request: Process] → [HTTP Request: Download] → [Set: Build Filename] → [Google Drive: Upload]
```

> **Note**: The API returns the original filename unchanged. The "Set: Build Filename" step is optional and only needed if you want to customize filenames. All processing metadata (mode, preset, file sizes, reduction %) is available in the API response for later use.

### Node Configuration Details

#### 1. Schedule Trigger

- **Cron Expression**: `0 2 * * *` (Daily at 2 AM)

#### 2. Google Drive: List Files

- **Operation**: List
- **Folder ID**: Your Google Drive folder ID
- **Filters**:
  - MIME Type: `application/pdf`
  - Options: Return All Results

#### 3. Split In Batches

- **Batch Size**: 1 (process one at a time)

#### 4. Google Drive: Download

- **Resource**: File
- **Operation**: Download
- **File ID**: `={{ $json.id }}`
- **Binary Property**: `data`

#### 5. HTTP Request: Process PDF

- **Method**: POST
- **URL**: `http://localhost:8502/api/process`
- **Body Content Type**: Multipart-Form Data
- **Body Parameters**:
  
  ```text
  file: ={{ $binary.data }}
  mode: auto
  preset: balanced
  language: eng
  ```

#### 6. HTTP Request: Download

- **Method**: GET
- **URL**: `=http://localhost:8502/api/download/{{ $json.file_id }}`
- **Response Format**: File
- **Binary Property**: `data`

#### 7. Google Drive: Upload (Simple Workflow)

- **Operation**: Upload
- **File Name**: `={{ $('Google Drive: Download').item.json.name }}`
- **Binary Data**: Yes
- **Binary Property**: `data`
- **Parent Folder ID**: Your output folder ID

> **Note**: The API returns the file with its original filename unchanged. Use the original name from Google Drive Download node.

#### 7-8. Set: Build Filename + Upload (Advanced Workflow - Optional)

This node is **optional** and only needed if you want custom filenames. The API returns the original filename by default.

**Set Node Configuration:**

- **Operation**: Set
- **Keep Only Set**: No
- **Values to Set**:
  - **Name**: `originalFilename`
  - **Value**: `={{ $('Google Drive: Download').item.json.name.replace('.pdf', '') }}`
  - **Name**: `newFilename`
  - **Value**: `={{ $json.originalFilename }} - {{ $('HTTP Request: Process').item.json.preset }}.pdf`

**Example Output**: `Invoice_2024` becomes `Invoice_2024 - balanced.pdf`

Alternative with size reduction percentage:

```javascript
={{ $json.originalFilename }} - {{ $('HTTP Request: Process').item.json.preset }} ({{ $('HTTP Request: Process').item.json.reduction_percent }}% smaller).pdf
```

**Example Output**: `Invoice_2024 - balanced (45.2% smaller).pdf`

**Upload Node Configuration:**

- **Operation**: Upload
- **File Name**: `={{ $json.newFilename }}`
- **Binary Data**: Yes
- **Binary Property**: `data`
- **Parent Folder ID**: Your output folder ID

### Complete n8n JSON (Google Drive)

```json
{
  "name": "PDF OCR Batch - Google Drive",
  "nodes": [
    {
      "parameters": {
        "rule": {
          "interval": [
            {
              "field": "cronExpression",
              "expression": "0 2 * * *"
            }
          ]
        }
      },
      "name": "Daily at 2 AM",
      "type": "n8n-nodes-base.scheduleTrigger",
      "typeVersion": 1,
      "position": [240, 300]
    },
    {
      "parameters": {
        "operation": "list",
        "folderId": {
          "__rl": true,
          "value": "YOUR_FOLDER_ID_HERE",
          "mode": "id"
        },
        "filters": {
          "query": "mimeType='application/pdf'"
        },
        "options": {
          "returnAll": true
        }
      },
      "name": "List PDFs from Drive",
      "type": "n8n-nodes-base.googleDrive",
      "typeVersion": 3,
      "position": [440, 300],
      "credentials": {
        "googleDriveOAuth2Api": {
          "id": "YOUR_CREDENTIALS_ID",
          "name": "Google Drive account"
        }
      }
    },
    {
      "parameters": {
        "batchSize": 1
      },
      "name": "Process One at a Time",
      "type": "n8n-nodes-base.splitInBatches",
      "typeVersion": 3,
      "position": [640, 300]
    },
    {
      "parameters": {
        "operation": "download",
        "fileId": {
          "__rl": true,
          "value": "={{ $json.id }}",
          "mode": "id"
        },
        "options": {
          "binaryPropertyName": "data"
        }
      },
      "name": "Download from Drive",
      "type": "n8n-nodes-base.googleDrive",
      "typeVersion": 3,
      "position": [840, 300],
      "credentials": {
        "googleDriveOAuth2Api": {
          "id": "YOUR_CREDENTIALS_ID",
          "name": "Google Drive account"
        }
      }
    },
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
      "typeVersion": 3,
      "position": [1040, 300]
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
      "name": "Download Processed",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 3,
      "position": [1240, 300]
    },
    {
      "parameters": {
        "assignments": {
          "assignments": [
            {
              "name": "originalFilename",
              "value": "={{ $('Google Drive: Download').item.json.name.replace('.pdf', '') }}",
              "type": "string"
            },
            {
              "name": "qualityPreset",
              "value": "balanced",
              "type": "string"
            },
            {
              "name": "newFilename",
              "value": "={{ $json.originalFilename }} - {{ $json.qualityPreset }}.pdf",
              "type": "string"
            }
          ]
        },
        "options": {}
      },
      "name": "Build Filename",
      "type": "n8n-nodes-base.set",
      "typeVersion": 3,
      "position": [1440, 300]
    },
    {
      "parameters": {
        "operation": "upload",
        "name": "={{ $json.newFilename }}",
        "parents": {
          "__rl": true,
          "value": "YOUR_OUTPUT_FOLDER_ID",
          "mode": "id"
        },
        "options": {
          "binaryData": true,
          "binaryPropertyName": "data"
        }
      },
      "name": "Upload to Drive",
      "type": "n8n-nodes-base.googleDrive",
      "typeVersion": 3,
      "position": [1440, 300],
      "credentials": {
        "googleDriveOAuth2Api": {
          "id": "YOUR_CREDENTIALS_ID",
          "name": "Google Drive account"
        }
      }
    }
  ],
  "connections": {
    "Daily at 2 AM": {
      "main": [
        [
          {
            "node": "List PDFs from Drive",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "List PDFs from Drive": {
      "main": [
        [
          {
            "node": "Process One at a Time",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Process One at a Time": {
      "main": [
        [
          {
            "node": "Download from Drive",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Download from Drive": {
      "main": [
        [
          {
            "node": "Process PDF",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Process PDF": {
      "main": [
        [
          {
            "node": "Download Processed",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Download Processed": {
      "main": [
        [
          {
            "node": "Build Filename",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Build Filename": {
      "main": [
        [
          {
            "node": "Upload to Drive",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  }
}
```

## Workflow 3: Dropbox Batch Processing

Process PDFs from Dropbox folder.

### Node Configuration

#### 1. Dropbox: List Files

- **Operation**: List
- **Folder Path**: `/PDFs/To Process/`

#### 2. Dropbox: Download

- **Operation**: Download
- **Path**: `={{ $json.path_display }}`
- **Binary Property**: `data`

#### 3. Process + Download (same as above)

#### 4. Dropbox: Upload

- **Operation**: Upload
- **Path**: `=/PDFs/Processed/{{ $json.name.replace('.pdf', '_processed.pdf') }}`
- **Binary Data**: Yes

## Workflow 4: Email Attachments Processing

Process PDF attachments from incoming emails.

### Nodes Setup

```text
[Email Trigger] → [Filter PDFs] → [HTTP Request: Process] → [HTTP Request: Download] → [Send Email with Attachment]
```

### Node Details

#### 1. Email Trigger (IMAP)

- **Operation**: Trigger
- **Mailbox**: INBOX
- **Options**: Download Attachments

#### 2. Filter (IF Node)

- **Condition**: `{{ $json.attachments[0].mimeType }}` equals `application/pdf`

#### 3. HTTP Request: Process

- **Body Parameters**:
  
  ```text
  file: ={{ $binary.attachment_0 }}
  mode: auto
  preset: balanced
  ```

#### 4. Send Email

- **To**: `={{ $json.from.address }}`
- **Subject**: `Processed: {{ $json.subject }}`
- **Attachments**: Binary property `data`

## Filename Formatting Examples

The "Set: Build Filename" node can be customized to your preferred naming convention. All examples use data from the API response (`$('HTTP Request: Process').item.json`).

### Basic: Filename + Quality

```javascript
={{ $json.originalFilename }} - {{ $('HTTP Request: Process').item.json.preset }}.pdf
```

**Output**: `Contract_2024 - balanced.pdf`

### With Size Reduction

```javascript
={{ $json.originalFilename }} - {{ $('HTTP Request: Process').item.json.preset }} ({{ $('HTTP Request: Process').item.json.reduction_percent.toFixed(1) }}% smaller).pdf
```

**Output**: `Contract_2024 - balanced (52.3% smaller).pdf`

### With Date Stamp

```javascript
={{ $json.originalFilename }} - {{ $('HTTP Request: Process').item.json.preset }} - {{ $now.format('yyyy-MM-dd') }}.pdf
```

**Output**: `Contract_2024 - balanced - 2025-10-02.pdf`

### With Size Info (MB)

```javascript
={{ $json.originalFilename }} - {{ $('HTTP Request: Process').item.json.preset }} - {{ ($('HTTP Request: Process').item.json.output_size / 1024 / 1024).toFixed(1) }}MB.pdf
```

**Output**: `Contract_2024 - balanced - 3.2MB.pdf`

### With Processing Mode

```javascript
={{ $json.originalFilename }} - {{ $('HTTP Request: Process').item.json.mode }} - {{ $('HTTP Request: Process').item.json.preset }}.pdf
```

**Output**: `Contract_2024 - auto - balanced.pdf`

### Custom Prefix for Organization

```javascript
=PROCESSED_{{ $json.originalFilename }}_{{ $('HTTP Request: Process').item.json.preset }}.pdf
```

**Output**: `PROCESSED_Contract_2024_balanced.pdf`

## Advanced Features

### Error Handling

Add error workflow to handle failures:

```json
{
  "parameters": {
    "conditions": {
      "string": [
        {
          "value1": "={{ $json.status }}",
          "operation": "notEqual",
          "value2": "success"
        }
      ]
    }
  },
  "name": "Check Success",
  "type": "n8n-nodes-base.if",
  "typeVersion": 1,
  "position": [1040, 300]
}
```

### Notification on Completion

Add Slack/Discord/Email notification:

```text
[After Processing] → [Set Node] → [Slack: Send Message]
```

Message template:

```text
Processed {{ $json.processed_count }} PDFs
Total reduction: {{ $json.total_reduction_mb }} MB
Time: {{ $json.total_time }}s
```

### Quality Selection Based on File Size

Use IF node to choose preset based on file size:

```javascript
// Expression for preset selection
{{ $binary.data.fileSize > 10485760 ? 'smallest' : 'balanced' }}
// If file > 10MB, use 'smallest', else 'balanced'
```

### Parallel Processing

For faster batch processing with multiple files:

1. Remove "Split In Batches" node
2. Set HTTP Request node to handle multiple items
3. Add "Merge" node after download to consolidate results

**⚠️ Warning**: Parallel processing uses more memory. Start with batch size 3-5.

## Configuration Templates

### Conservative (Safe, Slow)

```text
mode: auto
preset: balanced
jobs: 2
Batch Size: 1
```

### Balanced (Recommended)

```text
mode: auto
preset: balanced
jobs: 4
Batch Size: 1
```

### Aggressive (Fast, High Memory)

```text
mode: compress (if text already exists)
preset: smallest
jobs: 8
Batch Size: 3 (parallel)
```

### Archival Quality

```text
mode: ocr
preset: archival
pdfa: true
jobs: 4
```

## Testing Your Workflow

### 1. Test with Single File

- Temporarily add a "Stop and Error" node after first file
- Verify output quality before full batch

### 2. Monitor First Run

```bash
# Watch API logs
docker logs -f pdf-ocr-compress

# Check memory usage
docker stats pdf-ocr-compress
```

### 3. Validate Results

Add a "Function" node to check file sizes:

```javascript
const original = $binary.data.fileSize;
const processed = $('Download Processed').item.binary.data.fileSize;
const reduction = ((original - processed) / original * 100).toFixed(1);

return {
  json: {
    original_mb: (original / 1024 / 1024).toFixed(2),
    processed_mb: (processed / 1024 / 1024).toFixed(2),
    reduction_percent: reduction
  }
};
```

## Performance Tips

1. **Process during off-hours** - Schedule for nights/weekends
2. **Start small** - Test with 5-10 files first
3. **Monitor memory** - Docker container has 2GB limit by default
4. **Adjust jobs parameter** - Match to Docker CPU allocation
5. **Use local processing** - Faster than network uploads
6. **Clean up processed files** - Archive or delete after success

## Troubleshooting

### Files Not Processing

```javascript
// Add debug node to check binary data
return {
  json: {
    hasBinary: !!$binary.data,
    fileName: $json.name,
    fileSize: $binary.data?.fileSize
  }
};
```

### Timeout Errors

In HTTP Request node, add:

- **Timeout**: 600000 (10 minutes)
- **Retry on Fail**: Yes
- **Max Tries**: 3

### Memory Issues

```bash
# Increase Docker memory limit
# In docker-compose.yml:
deploy:
  resources:
    limits:
      memory: 4G  # Increase to 4GB
```

### API Not Responding

```bash
# Check if container is running
docker ps

# Restart if needed
docker-compose restart

# Check logs
docker logs pdf-ocr-compress
```

## Example: Complete Production Workflow

```text
[Schedule: Daily 2 AM]
    ↓
[Google Drive: List PDFs]
    ↓
[IF: File Size > 100MB → Skip] ← Large files filter
    ↓
[Split In Batches: Size 1]
    ↓
[Google Drive: Download]
    ↓
[HTTP Request: Process]
    ↓
[IF: Status = Success]
    ↓ (true)                    ↓ (false)
[HTTP Request: Download]    [Slack: Send Error]
    ↓
[Google Drive: Upload]
    ↓
[Google Drive: Delete Original]
    ↓
[Function: Calculate Stats]
    ↓
[Slack: Send Summary]
```

## Security Notes

- API has no authentication - use firewall or VPN
- For production: Add API key authentication
- Store credentials securely in n8n credential manager
- Use environment variables for API URL

## Next Steps

1. Import one of the workflow JSONs above
2. Update folder paths/credentials
3. Test with 1-2 files
4. Adjust settings based on results
5. Enable schedule trigger for automation

Need help? Check API logs: `docker logs -f pdf-ocr-compress`
