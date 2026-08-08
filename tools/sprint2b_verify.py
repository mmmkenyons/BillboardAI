"""Sprint 2B verification: BrandProfile → RenderContext → Render."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.brand_profile import BrandProfileBuilder
from gui.models.render_context import RenderContext
from engine.renderer.renderer import render_billboard

# Load the scraped data
json_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "engine", "output", "json", "jimwoodsroofing.json",
)
with open(json_path, "r") as f:
    data = json.load(f)

# Build BrandProfile
bp = BrandProfileBuilder.from_scrape_data(data)

print("=== BRANDPROFILE SUMMARY ===")
print(f"Company: {bp.company_name}")
print(f"Website: {bp.website}")
print(f"Domain: {bp.domain}")
print(f"Headline: {bp.headline}")
print(f"Ad Copy: {bp.ad_copy}")
print(f"Colors: {bp.colors}")
if bp.logo:
    print(
        f"Logo: {os.path.basename(bp.logo.path)} "
        f"({bp.logo.width}x{bp.logo.height}, {bp.logo.format}, "
        f"alpha={bp.logo.has_alpha})"
    )
else:
    print("Logo: None")
print(f"Assets: {len(bp.assets)}")
print(f"Hero URL: {bp.hero_url}")
print(f"Hero Assets: {len(bp.hero_assets)}")
print(f"Quality Score: {bp.quality_score}")
print(f"Vision Score: {bp.vision_score}")
print(f"Screenshot: {bp.screenshot_path}")
print(f"Source Metadata keys: {list(bp.source_metadata.keys())}")
legacy = bp.source_metadata.get("legacy_logo_path", "N/A")
print(f"Legacy logo_path preserved: {legacy}")

# Build RenderContext from BrandProfile
ctx = RenderContext.from_brand_profile(bp, template="contractor")
print()
print("=== RENDERCONTEXT FROM BRANDPROFILE ===")
print(f"Company: {ctx.company_name}")
print(f"Headline: {ctx.headline}")
print(f"Logo: {ctx.logo_image}")
print(f"Hero: {ctx.hero_image}")
print(f"Background: {ctx.background_image}")
print(f"Colors: {ctx.brand_colors}")
print(f"Quality: {ctx.quality_score}")
print(f"Source URL: {ctx.source_url}")

# Render from BrandProfile
spec = ctx.to_render_spec()
out = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "engine", "output", "jimwoods_brandprofile_test.png",
)
render_billboard(spec, out)
print(f"\nRender output: {out}")
print(f"Render file exists: {os.path.exists(out)}")
print(f"Render file size: {os.path.getsize(out)} bytes")

# Also verify from_scrape backward compat
ctx2 = RenderContext.from_scrape(data, template="contractor")
print()
print("=== from_scrape() BACKWARD COMPAT ===")
print(f"Company: {ctx2.company_name}")
print(f"Headline: {ctx2.headline}")
print(f"Logo: {ctx2.logo_image}")
print(f"Hero: {ctx2.hero_image}")
print(f"Quality: {ctx2.quality_score}")

# Verify both produce same result
print()
print("=== CONSISTENCY CHECK ===")
print(f"Same company: {ctx.company_name == ctx2.company_name}")
print(f"Same headline: {ctx.headline == ctx2.headline}")
print(f"Same logo: {ctx.logo_image == ctx2.logo_image}")
print(f"Same hero: {ctx.hero_image == ctx2.hero_image}")
print(f"Same quality: {ctx.quality_score == ctx2.quality_score}")
print(f"Same source_url: {ctx.source_url == ctx2.source_url}")
print(f"Same brand_colors: {ctx.brand_colors == ctx2.brand_colors}")