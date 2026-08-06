# BillboardAI Roadmap

## Version 0.1 (Current) — Professional Desktop Renderer

- Desktop application for scraping websites and producing billboard mockups
- Single-site and batch processing
- Playwright-based scraping with asset caching
- Template-based billboard design engine
- PIL-based image rendering with dynamic typography
- SmartLead CSV export
- Cloudinary upload support

## Version 0.2 — Creative Workspace

- Project management
- Multiple concepts per project
- Gallery view
- Autosave
- Editable copy

## Version 0.3 — Sales Studio

- Batch generation
- CSV import
- SmartLead export
- Cold email generation
- Campaign packaging

## Version 0.4 — Creative Intelligence

- Multiple AI-generated concepts
- Headline scoring
- CTA scoring
- Brand consistency scoring
- Automatic best concept selection

## Version 1.0 — Commercial Release

- Installer
- Licensing
- Auto-update
- Crash reporting
- User settings
- Documentation

---

## Project Structure

```
BillboardAI/

│
├── main.py
├── config.py
├── requirements.txt
│
├── scraper.py
├── analyzer.py
├── designer.py
├── renderer.py
├── uploader.py
├── smartlead.py
│
├── templates/
│
│     contractor.py
│     realtor.py
│     dentist.py
│
├── fonts/
│
│     Montserrat-Bold.ttf
│     Montserrat-Regular.ttf
│     BebasNeue.ttf
│
├── assets/
│
│     cart_corral.jpg
│
├── cache/
│
│     html/
│     logos/
│     screenshots/
│
├── output/
│
│     images/
│     csv/
│
└── logs/
```

Notice...

Everything is separated.

Nothing is mixed together.

---

## Technical Design Notes

### Scraper 2.0

Instead of

```
requests.get()
```

We'll use Playwright.

That means

```
Website
      ↓
Javascript executes
      ↓
Page fully loads
      ↓
Screenshot
      ↓
HTML
      ↓
CSS
      ↓
Assets
```

We now have everything.

---

### Logo Detection 2.0

Instead of

```
Find class="logo"
```

We'll score every image.

Example

```
logo.svg

Score 100
```

```
header_logo.png

Score 95
```

```
favicon.png

Score 80
```

```
hero-house.jpg

Score 20
```

Pick highest score.

If confidence is low

↓

Use OpenGraph image.

If still low

↓

Use screenshot crop.

---

### Color Detection

Don't read CSS.

Analyze the logo.

```
Logo

↓

KMeans

↓

Top 5 colors

↓

Ignore

white

black

gray

↓

Pick dominant
```

This is how Adobe does it.

---

### AI Headline

Instead of

```
Top Rated Roofing Experts
```

we'll scrape

```
H1

Title

Meta

Hero
```

Suppose homepage says

```
Colorado's Storm Damage Specialists
```

Billboard becomes

```
Storm Damage Specialists
```

Much better.

---

### Hero Image

We'll locate

```
Largest visible image
```

Download it.

Crop intelligently.

Use as billboard background.

---

### Designer

We'll build templates.

Example

```
Dark

Logo

Headline

Phone
```

---

```
White

Large Logo

Website
```

---

```
Photo

Overlay

Headline

CTA
```

---

```
Premium

Gold

Minimal
```

The AI picks one.

---

### Dynamic Fonts

Instead of

```
72 pt
```

always...

```
while width > max
font -= 2
```

Perfect fit.

---

### Perspective

Current

```
Warp

Paste
```

New

```
Warp

↓

Alpha

↓

Lighting

↓

Noise

↓

Blur

↓

Sharpen

↓

Shadow

↓

Reflection
```

Looks installed.

---

### AI Quality Check

Before upload

Score

```
Logo

Headline

Contrast

Alignment

Readability
```

If score

<80

Generate another layout.

---

### Logging

Console becomes

```
ABC Roofing

✓ Website

✓ HTML

✓ Screenshot

✓ Logo

✓ Colors

✓ Phone

✓ Hero

✓ Template 3

✓ Perspective

✓ Uploaded

17 seconds
```

---

### Smartlead

Output

```
First Name

Last Name

Email

Company

Website

Custom_Image

Headline
```

Ready to import.

---

### Even Better...

I wouldn't stop there.

I'd add AI vision.

GPT-4.1 Vision (or another vision model) can look at the rendered billboard and answer:

```
Is this believable?

Does it look photoshopped?

Is the text readable?

Does it look premium?
```

If not...

Generate another.

---

### My Favorite Feature

This is the one I think will make people reply.

Instead of

```
ABC Roofing
```

every billboard says

```
Serving Castle Rock Since 1997
```

or

```
Insurance Claim Specialists
```

or

```
1,200 Five-Star Reviews
```

All scraped automatically.

Every image feels custom.

---

## How I'd Build This

I would not dump 3,000 lines into one file. I would build it like commercial software:

### Milestone Tracking

- [x] Milestone 1 (Week 1)
  - [x] Website scraper (Playwright)
  - [x] Logo detection
  - [x] Brand color extraction
  - [x] Asset caching
  - [x] JSON output

- [x] Milestone 2 (Week 2)
  - [x] Billboard design engine
  - [x] Dynamic typography
  - [x] Multiple templates
  - [x] Perspective rendering
  - [x] Local image output

- [x] Milestone 3 (Week 3)
  - [x] Cloudinary uploads
  - [x] Smartlead CSV generation
  - [x] Batch processing
  - [x] Resume/retry support
  - [x] Detailed logging

- [x] Milestone 4 (Week 4)
  - [x] AI copy extraction
  - [x] AI layout selection
  - [x] Quality scoring
  - [ ] Automatic regeneration of weak mockups

## How to get started

1. **Install Python 3.12** from python.org.
2. **Install Visual Studio Code**.
3. Open a terminal and create your project:

```
mkdir BillboardAI
cd BillboardAI
python -m venv .venv
```

4. Activate the virtual environment:

- Windows:

```
.venv\Scripts\activate
```

- macOS/Linux:

```
source .venv/bin/activate
```

5. Install the packages listed above.
6. Run:

```
playwright install chromium
```

7. Create the folder structure shown above.
8. Add your fonts (Montserrat is a great default) and your cart corral background image.
9. Commit the empty project to Git so you can safely iterate:

## Batch usage

Use the main script in batch mode to process multiple URLs and export Smartlead data:

```
python main.py --batch-file urls.txt --output-csv output/smartlead.csv --template contractor --upload
```

The batch processor will save progress in `output/batch_status.json` and resume skipped URLs on the next run.

10. Commit frequently after each milestone.

```
git init
git add .
git commit -m "Initial BillboardAI project structure"
```

---

## One recommendation

Because this is becoming a substantial application, I would **not** continue building it solely through chat responses. The right way to do this is to create a real project with proper source files, testing, and iterative development. That way, each module is complete and runnable before moving to the next.

I can absolutely help you build every part of it, but we'll end up with a much more reliable result if we develop it as a structured codebase rather than trying to squeeze thousands of lines of production code into individual chat messages.