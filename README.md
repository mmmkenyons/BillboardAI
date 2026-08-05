# BillboardAI

A structured billboard mockup generator for scraping website branding and turning it into ad-ready mockups.

## Setup

1. Create a virtual environment:

   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Install Playwright browsers:

   ```powershell
   playwright install chromium
   ```

4. Create a `.env` file with Cloudinary credentials:

   ```env
   CLOUDINARY_CLOUD_NAME=your_cloud_name
   CLOUDINARY_API_KEY=your_api_key
   CLOUDINARY_API_SECRET=your_api_secret
   ```

## Usage

### Single-site scrape and render

```powershell
python main.py https://example.com --render --template auto
```

### Batch processing with CSV and upload

```powershell
python main.py --batch-file urls.txt --output-csv output/smartlead.csv --template auto --upload
```

### Smartlead CSV output
The CSV includes the following fields:

- First Name
- Last Name
- Email
- Company
- Website
- Custom_Image
- Headline
- Quality Score
- Quality Label
- Vision Score
- Vision Label

## Deployment

For local deployment, clone the repo, install dependencies, configure `.env`, and run `python main.py` as shown above. For server deployment, repeat these steps on a managed instance and use a scheduled task or script to execute batch commands.

## Project structure

- `main.py` - entry point
- `config.py` - shared settings and paths
- `scraper/` - website scraping and brand extraction
- `designer/` - billboard templates and layouts
- `renderer/` - image production and typography
- `uploader/` - cloud upload support
- `tests/` - unit tests

## Additional documentation
See `DEPLOYMENT.md` for full deployment instructions and recommended patterns.

## Helper scripts
- `deploy.ps1` — Windows deployment helper that installs dependencies, installs Playwright, and runs batch processing.
- `.env.example` — sample environment file for Cloudinary credentials.
