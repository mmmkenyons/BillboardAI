# BillboardAI Deployment Guide

## Overview
BillboardAI is a Python-based billboard mockup generator that scrapes website branding, generates ad copy and quality scores, renders mockups, and optionally uploads images to Cloudinary.

## Prerequisites
- Python 3.14 installed
- Git installed
- Cloudinary account and credentials (for upload support)
- Optional: PowerShell on Windows

## Environment variables
Create a `.env` file in the repository root with:

```env
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
```

## Local deployment
1. Clone the repository:

   ```powershell
   git clone <repo-url> BillboardAI
   cd BillboardAI
   ```

2. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

4. Install Playwright browsers:

   ```powershell
   playwright install chromium
   ```

5. Create `.env` with Cloudinary credentials.

6. Run the app:

   ```powershell
   python main.py https://example.com --render --template auto
   ```

## Batch usage
Process a file containing URLs one per line:

```powershell
python main.py --batch-file urls.txt --output-csv output/smartlead.csv --template auto --upload
```

This generates images, writes a Smartlead CSV, and uploads images when `--upload` is enabled.

## Deploying to a server
1. Provision a server with Python 3.14.
2. Clone the repo and install dependencies as above.
3. Add the `.env` file on the server.
4. Install Playwright browsers.
5. Run the same `python main.py` commands in a terminal or scheduled task.

## Recommended deployment patterns
- Run as a command-line utility on a workstation or server.
- Use a reproducible virtual environment and keep the repo up to date via Git.
- For scheduled batch work, wrap the `main.py` invocation in a script or task scheduler.

## Notes
- If uploads are not required, omit `--upload`.
- The CSV output includes quality and vision scoring fields.
- Keep Cloudinary credentials secure and do not commit `.env` to source control.
