# Upload Projects to R2

This script uploads dreamwright projects to the Cloudflare R2 bucket for the webtoons showcase.

## Prerequisites

1. Python 3.8+ with the dreamwright virtual environment
2. R2 API credentials (see below)

## Setup

### 1. Install dependencies

```bash
cd /path/to/dreamwright
uv pip install boto3 python-dotenv
```

### 2. Configure credentials

Copy the example environment file:

```bash
cp apps/showcase/scripts/.env.example apps/showcase/scripts/.env
```

Edit `.env` with your credentials:

```env
CLOUDFLARE_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key_id
R2_SECRET_ACCESS_KEY=your_secret_access_key
```

### 3. Get R2 API credentials

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Navigate to **R2** > **Manage R2 API Tokens**
3. Click **Create API Token**
4. Select **Object Read & Write** permission
5. Choose the `webtoons-showcase` bucket (or all buckets)
6. Copy the **Access Key ID** and **Secret Access Key**

Your **Account ID** can be found in the dashboard URL or on the R2 overview page.

## Usage

```bash
# Activate the virtual environment
cd /path/to/dreamwright

# List available projects
.venv/bin/python apps/showcase/scripts/upload_projects.py --list

# Upload a specific project
.venv/bin/python apps/showcase/scripts/upload_projects.py dragon-mishap

# Upload multiple projects
.venv/bin/python apps/showcase/scripts/upload_projects.py dragon-mishap the-last-hunter

# Upload all projects
.venv/bin/python apps/showcase/scripts/upload_projects.py
```

## What gets uploaded

For each project, the script:

1. **Transforms** `project.json` → `webtoon.json` (viewer-compatible format)
2. **Uploads** character portraits and sheets
3. **Uploads** chapter panel images
4. **Uploads** cover image (or uses first character portrait as fallback)

### R2 bucket structure

```
webtoons-showcase/
├── {project-name}/
│   ├── webtoon.json
│   └── assets/
│       ├── covers/
│       │   └── series_cover.jpg
│       ├── characters/
│       │   ├── {char_id}_portrait.png
│       │   └── {char_id}.png
│       └── chapters/
│           └── ch{N}/
│               └── ch{N}_s{M}_p{P}.jpg
```

## Environment variables

| Variable | Description | Required |
|----------|-------------|----------|
| `CLOUDFLARE_ACCOUNT_ID` | Your Cloudflare account ID | Yes |
| `R2_ACCESS_KEY_ID` | R2 API token access key | Yes |
| `R2_SECRET_ACCESS_KEY` | R2 API token secret key | Yes |
| `R2_BUCKET_NAME` | R2 bucket name (default: `webtoons-showcase`) | No |
| `PROJECTS_DIR` | Path to projects directory | No |

## Troubleshooting

### "boto3 is required"

Install the dependency:
```bash
uv pip install boto3
```

### "Missing required environment variables"

Make sure your `.env` file exists and contains all required credentials.

### Images not loading on the site

1. Check if the character ID format matches (underscores vs hyphens)
2. Hard refresh the browser (`Cmd+Shift+R` or `Ctrl+Shift+R`)
3. Verify the image was uploaded: check the script output for errors
