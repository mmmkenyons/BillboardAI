# BillboardAI ROADMAP

> **Product direction:** BillboardAI is a sales-enablement and
> advertising-inventory monetization platform for local advertising, not merely
> an AI billboard-design tool. See **PRODUCT_VISION.md** for the full strategic
> positioning, principles, moat, and North Star.
>
> This roadmap reflects that reprioritization while preserving historical /
> completed milestone information. Statuses below are clearly labeled:
> `COMPLETED`, `CURRENT`, `NEXT`, `FUTURE`. Nothing is presented as finished
> unless it actually is.

---

## Completed

The foundational pipeline below is real, shipped, and directly supports the
sales-enablement vision (it becomes components of the larger workflow):

```
WebsiteScraper
  → normalized BrandAssets
  → BrandProfile
  → Business Intelligence
  → MessageStrategy
  → AdConcept
  → Creative / Layout
  → Physical Mockup
```

### Sprint 2D — Message Strategy Engine (COMPLETED)
- `engine/message_strategy.py` — determines WHAT a billboard should communicate
  given a BrandProfile, producing evidence-traceable `MessageStrategy`
  candidates (TRUST_LED, SERVICE_LED, OFFER_LED, LOCAL_AUTHORITY, PROBLEM_LED).
- Deterministic, evidence-first, no LLM/ML/external APIs.

### Sprint 2C — Business Intelligence (COMPLETED)
- `engine/scraper/business_intel.py` — build_context + extract_business_intel
  over live-scraped HTML (services, categories, differentiators, trust signals,
  awards, certifications, guarantees, years in business, location, etc.).

### BrandProfile Foundation (COMPLETED)
- `engine/brand_profile.py` — `BrandProfile` and `BrandProfileBuilder` consume
  normalized brand assets + business intelligence.

### Brand Asset Normalization (COMPLETED)
- Normalized `BrandAssets` (logo / hero) with confidence and provenance.

### Screenshot Validation & Capture Reliability (COMPLETED)
- `engine/scraper/capture.py`, `engine/scraper/validators.py` — pluggable
  validators (Dimension, Variance, Brightness, Entropy), `ScreenshotQuality`,
  rejection of invalid captures, 3-tier retry, `ScreenshotValidationError`
  surfaced in GUI, debug diagnostics gated by `BILLBOARD_DEBUG=1`.

### Sprint 4B — Screenshot Capture Audit (COMPLETED — Debug Mode Only)
- Pure audit of blank-screenshot regression (tnrroof.com) with baseline
  comparison; no code changes made; validation recommendation implemented in the
  Screenshot Validation milestone above.

---

## Current

### Sprint 2E — Ad Concept Engine (CURRENT — in verification)
- `engine/ad_concept.py` — decides HOW a billboard's information should be
  STRUCTURED VISUALLY: which elements to use, their visual roles, and their
  conceptual hierarchy (composition families: BRAND_DOMINANT, HERO_IMAGE,
  MESSAGE_DOMINANT, TRUST_AUTHORITY, LOCAL_AUTHORITY).
- Consumes the public `MessageStrategy` contract; evidence-first, deterministic,
  budget-disciplined; does NOT draw artwork / place pixels (scope lock for the
  future Artwork Layout Engine).
- Real-world verification tool: `tools/sprint2e_verify.py` (Jim Woods Roofing).
- Unit tests: `tests/test_ad_concept.py`.

---

## Next (Priority Order)

After the current concept-engine work, per the reprioritized roadmap:

1. **Finish Ad Concept Engine** — complete/land Sprint 2E (verify, test, commit).
2. **Build practical Creative Layout MVP** — turn AdConcepts into usable layouts
   (the "Artwork Layout Engine" that AdConcept deliberately defers to).
3. **Build persistent Project Workspace** — organize projects/businesses and
   persist rendered output (extends existing `Project`).
4. **Introduce Advertising Inventory / Placement data model** — make
   advertising inventory a first-class entity (availability, exclusivity,
   placement characteristics, pricing).
5. **Build Batch Prospect Import** — batch import of prospect lists.
6. **Build Batch Research / Brand Intelligence** — batch run of
   scrape → BrandAssets → BrandProfile → Business Intelligence.
7. **Build Batch Creative + Mockup Generation** — batch
   MessageStrategy → AdConcept → Creative/Layout → Mockup.
8. **Build Personalized Outreach Engine** — personalized outreach as part of
   the core workflow.
9. **Integrate campaign sending / outreach platform(s)** — e.g. Smartlead and
   similar; integrate with mature systems rather than recreating full CRM.

---

## Future

10. **Build lightweight Sales Pipeline** — track opportunities / stages,
    integrating with mature CRM/outreach systems where appropriate.
11. **Build retailer / physical Scene Library into the product workflow.**
12. **Add Performance Analytics / feedback loop** — connect inventory, prospect
    characteristics, BrandProfile evidence, message strategy, creative concept,
    outreach messaging, engagement, replies, meetings/proposals, wins/losses,
    contract value.
13. **Add cloud sync / multi-user capabilities when justified.**
14. **Expand to additional advertising formats** — keep architecture extensible
    beyond grocery-cart / billboard advertising.

> Creative / layout quality may continue improving incrementally without
> blocking the broader sales workflow (Product Principle 2).

---

## Historical — Sprint 4B Regression: Screenshot Capture Audit (COMPLETED — Debug Mode Only)

**Bug Split & Findings:**
- **Bug 1 (Highest Priority - Blank Screenshots in scraper/):** Confirmed. tnrroof.com produces pure white screenshot/hero (mean [255,255,255], stddev=0, variance=0). Baseline on example.com is good (mean ~237, stddev ~11, not uniform). Scraper capture (networkidle, full_page) works on baseline but fails on tnrroof (likely JS timing, render, or site-specific before screenshot). Analyzer vision_score low but doesn't block. First invalid point: save_screenshot() / analyze_scrape_data() → RenderContext.from_scrape() / _ingest_render_context() copies blank assets without validation. Logo missing, hero blank.
- **Bug 2 (ReRenderWorker State):** Downstream. First render succeeds (with blank), context ingested into Project, second re-render crashes due to invalid assumptions on hero/context in effective_render_context() and worker.

**Diagnostics Performed (Per User Instructions):**
- Instrumented and ran baseline (example.com, python.org) and tnrroof.com.
- Logs showed populated DOM on baseline, white uniform on tnrroof despite content (timing/JS issue).
- Git diff 18687b3 vs current: Capture logic identical (no change in wait, launch, viewport). Regression in GUI ingest post-Sprint 4B.
- Console/network: No major errors in baseline; tnrroof had some JS warnings but main issue is white render.
- Success criteria answered: DOM populated on both, but screenshot white on tnrroof (render/timing, not empty body). Baseline succeeds.

**Validation Recommendation (Next Milestone Before 4C):**
- Add validate_screenshot() (variance > 10, stddev >5, not all-white, dimensions >300px).
- In save_screenshot(): validate, retry with 'domcontentloaded' if bad, else mark failed (None path, log).
- Prevent blank from reaching RenderContext/Project (in from_scrape and ingest).
- This eliminates garbage input; Bug 2 can then be fixed separately (graceful fallback in re-render for missing hero).

**No Code Changes Made:** Pure audit, logs, baseline comparison, and ROADMAP update per "Do not implement new features. Enter Debug Mode only." Task complete.

(Full logs and artifacts in debug_capture/ if generated; variance confirmed via PIL/np on assets.)

## Sprint: Screenshot Validation & Capture Reliability (Completed)

**Goals Achieved:**
- **Validate before RenderContext:** New `ScreenshotCaptureService` (engine/scraper/capture.py) with pluggable validators (engine/scraper/validators.py: Dimension, Variance, Brightness, Entropy using numpy/cv2). `ScreenshotQuality` dataclass provides score, variance, stddev, brightness, entropy, reason.
- **Reject invalid captures:** Thresholds (variance >10, stddev >5, not uniform white/black, dims >300px, entropy >1.0). Early exit on first failure.
- **Meaningful errors:** `ScreenshotValidationError` raised from scraper (never reaches RenderContext/Project). GUI (engine_bridge.py, workers, project.py) catches and surfaces "Unable to capture a usable screenshot..." with warnings/capture_error. No placeholders or crashes.
- **Improved robustness:** 3-tier retry (networkidle → load+fonts.ready+2s → scroll+wait). JS-heavy sites get additional readiness checks.
- **Diagnostics preserved:** Gated by `BILLBOARD_DEBUG=1` (config.py). Rejected screenshots saved to `output/debug/rejected/` with reason/timestamp. Full diagnostics logged.
- **Clean boundary:** Scraper orchestration only accepts valid `ScreenshotResult`. RenderContext.from_scrape assumes valid input. Project.set_render_context guards against garbage. Bug 2 prevented by design.

**Success Criteria Met:**

✅ example.com captures successfully (high variance/entropy).
✅ tnrroof.com raises clear `ScreenshotValidationError` (low_variance/uniform_white) - no blank render.
✅ No blank screenshots reach RenderContext, project.json, or renderer.
✅ GUI displays meaningful capture error (no gray placeholder).
✅ "Generate Again" / re-render no longer crashes on stale blank context (guard in project.py).
✅ All regression tests pass (test_render_context.py, CLI tests).
✅ Diagnostics available in debug mode (rejected PNGs, logs).

**Implementation Notes:**
- Phased: Foundation (validators/quality) → CaptureService → Scraper → GUI → Tests.
- No new deps; entropy via numpy histogram.
- Updated config.py, designer.py (None guard), engine_bridge.py, workers, models, tests.
- ROADMAP/PROJECT_BOARD updated. Ready for Bug 2 and Sprint 4C.

(Artifacts in output/debug/rejected/ for tnrroof; variance/entropy confirmed.)

## Previous Sprints
(Previous content omitted for brevity; see git history.)
