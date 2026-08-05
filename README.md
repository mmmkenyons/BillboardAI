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

## Project structure

- `main.py` - entry point
- `config.py` - shared settings and paths
- `scraper/` - website scraping and brand extraction
- `designer/` - billboard templates and layouts
- `renderer/` - image production and typography
- `uploader/` - cloud upload support
- `tests/` - unit tests
