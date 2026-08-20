"""Brand asset and brand profile data models for BillboardAI.

BrandAsset represents a VALIDATED visual image asset with real image metadata.
It is NOT used for arbitrary downloaded files — only for confirmed raster images.

BrandProfile is the normalized business/brand object between raw website scraping
and downstream concept/render preparation. It is BUSINESS / BRAND INTELLIGENCE,
not a paint/render contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import os
import re

from .person_personalization import PersonFacts, choose_personalization


# ---------------------------------------------------------------------------
# BrandAsset (Sprint 2A — unchanged)
# ---------------------------------------------------------------------------

@dataclass
class BrandAsset:
    """A validated visual brand asset with real image metadata.

    Only instantiate after content-based validation confirms the file
    is a supported raster image (PNG, JPEG, WEBP, etc.).

    Attributes:
        path: Absolute or relative filesystem path to the normalized file.
        source_url: Original download URL.
        asset_type: Semantic role (e.g. "logo", "hero", "generic").
        mime_type: Detected MIME type (e.g. "image/png").
        format: Detected image format (e.g. "PNG", "JPEG", "WEBP").
        width: Image width in pixels.
        height: Image height in pixels.
        aspect_ratio: width / height as a float.
        has_alpha: Whether the image has an alpha/transparency channel.
        file_size: File size in bytes.
        quality_score: Reserved for future ranking (default 0.0).
        selection_score: Reserved for future ranking (default 0.0).
        confidence: Confidence in this asset being a valid brand asset (0.0-1.0).
    """

    path: str
    source_url: str
    asset_type: str = "generic"
    mime_type: str = ""
    format: str = ""
    width: int = 0
    height: int = 0
    aspect_ratio: float = 0.0
    has_alpha: bool = False
    file_size: int = 0
    quality_score: float = 0.0
    selection_score: float = 0.0
    confidence: float = 1.0
    role: str = "OTHER"
    person_relevance_score: float = 0.0
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary for JSON output."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BrandAsset:
        """Deserialize from a dictionary."""
        # Filter to only known fields to be forward-compatible
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


ROLE_PERSON_PROFILE = "PERSON_PROFILE"
ROLE_PERSON_HEADER = "PERSON_HEADER"
ROLE_BUSINESS_LOGO = "BUSINESS_LOGO"
ROLE_PROPERTY_LISTING = "PROPERTY_LISTING"
ROLE_GENERIC_HERO = "GENERIC_HERO"
ROLE_SCREENSHOT = "SCREENSHOT"
ROLE_ICON = "ICON"
ROLE_OTHER = "OTHER"


def _norm_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _name_tokens(name: str) -> list[str]:
    return [part for part in _norm_text(name).split() if len(part) > 1]


def _contains_full_name(text: str, name: str) -> bool:
    tokens = _name_tokens(name)
    if len(tokens) < 2:
        return False
    norm = f" {_norm_text(text)} "
    return f" {' '.join(tokens)} " in norm


def _looks_like_person_profile_url(url: str) -> bool:
    text = _norm_text(url)
    return any(marker in text.split() for marker in ("agent", "profile", "person", "provider", "attorney", "advisor", "realtor", "team"))


def _quality_bucket(asset: BrandAsset) -> str:
    if asset.width < 120 or asset.height < 120:
        return "too_small"
    if asset.width < 180 or asset.height < 180:
        return "marginal"
    return "usable"


def classify_brand_assets(
    assets: list[BrandAsset],
    *,
    contact_name: str = "",
    page_url: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assign lightweight roles and person relevance evidence to image assets.

    This is deterministic metadata scoring only; it never identifies a face from
    pixels.  It uses source URL/path/alt-like URL text, dimensions, page title,
    and explicit prospect contact context when available.
    """
    meta = metadata if isinstance(metadata, dict) else {}
    title_text = " ".join(
        str(v or "")
        for v in (
            meta.get("title"),
            meta.get("description"),
            (meta.get("og") or {}).get("og:title") if isinstance(meta.get("og"), dict) else "",
            (meta.get("twitter") or {}).get("twitter:title") if isinstance(meta.get("twitter"), dict) else "",
        )
    )
    person_context = bool(contact_name and (_contains_full_name(title_text, contact_name) or _looks_like_person_profile_url(page_url)))

    diagnostics: list[dict[str, Any]] = []
    for asset in assets:
        existing_evidence = [str(item) for item in (asset.evidence or [])]
        dom_context = " ".join(
            item.split(":", 1)[1]
            for item in existing_evidence
            if item.startswith("dom_context:") and ":" in item
        )
        text = " ".join([asset.source_url or "", asset.path or "", asset.asset_type or "", dom_context])
        norm = _norm_text(text)
        evidence: list[str] = []
        role = ROLE_OTHER
        score = 0.0

        if asset.asset_type == "logo" or "logo" in norm:
            role = ROLE_BUSINESS_LOGO
            evidence.append("logo_text")
        elif asset.width < 120 or asset.height < 120 or any(word in norm.split() for word in ("icon", "favicon", "sprite")):
            role = ROLE_ICON
            evidence.append("icon_or_tiny")
        elif any(word in norm.split() for word in ("listing", "mls", "property", "homes", "house", "gallery")):
            role = ROLE_PROPERTY_LISTING
            evidence.append("property_listing_text")
        elif any(word in norm.split() for word in ("hero", "header", "banner", "cover")):
            role = ROLE_GENERIC_HERO
            evidence.append("hero_header_text")

        if contact_name and _contains_full_name(text, contact_name):
            score += 70
            evidence.append("source_path_or_dom_contains_full_contact_name")
        if contact_name and _contains_full_name(title_text, contact_name):
            score += 20
            evidence.append("page_title_contains_contact_name")
        if _looks_like_person_profile_url(page_url):
            score += 15
            evidence.append("profile_page_url")
        if any(word in norm.split() for word in ("agent", "profile", "headshot", "photo", "portrait", "person", "provider", "attorney", "advisor", "realtor", "owner")):
            score += 35
            evidence.append("person_role_text")

        aspect = asset.aspect_ratio or (asset.width / asset.height if asset.height else 0)
        if 0.65 <= aspect <= 1.35:
            score += 15
            evidence.append("square_or_portrait_ratio")
        elif 1.35 < aspect <= 2.4 and any(word in norm.split() for word in ("header", "banner", "cover", "hero")):
            score += 8
            evidence.append("person_header_ratio")

        if _quality_bucket(asset) == "too_small":
            score = min(score, 10)
            evidence.append("below_person_minimum")
        if role == ROLE_PROPERTY_LISTING:
            score = min(score, 25)
            evidence.append("property_images_not_person_focal")
        if score >= 95 and 0.65 <= aspect <= 1.35 and _quality_bucket(asset) != "too_small" and role != ROLE_PROPERTY_LISTING:
            role = ROLE_PERSON_PROFILE
        elif score >= 85 and role != ROLE_PROPERTY_LISTING and _quality_bucket(asset) != "too_small":
            role = ROLE_PERSON_HEADER if aspect > 1.35 else ROLE_PERSON_PROFILE
        elif role == ROLE_OTHER and asset.width >= 300 and asset.height >= 180:
            role = ROLE_GENERIC_HERO

        asset.role = role
        asset.person_relevance_score = round(score, 3)
        asset.selection_score = round(score + min(asset.width * asset.height / 20000, 40), 3)
        asset.evidence = sorted(set(evidence))
        diagnostics.append({
            "path": os.path.basename(asset.path or ""),
            "source_url": asset.source_url,
            "role": asset.role,
            "person_relevance_score": asset.person_relevance_score,
            "selection_score": asset.selection_score,
            "dimensions": f"{asset.width}x{asset.height}",
            "evidence": list(asset.evidence),
        })
    return {
        "person_oriented": bool(person_context),
        "target_contact_name": contact_name or "",
        "candidate_count": len(assets),
        "candidates": diagnostics,
    }


# ---------------------------------------------------------------------------
# BrandProfile (Sprint 2B)
# ---------------------------------------------------------------------------

BRAND_PROFILE_VERSION = 1


@dataclass
class BrandProfile:
    """Normalized business/brand intelligence object.

    Sits between raw WebsiteScraper output and RenderContext.
    Contains business identity, visual identity, and provenance metadata.

    This is BUSINESS INTELLIGENCE — not a paint/render contract.
    RenderContext remains the PAINT / RENDER CONTRACT.
    """

    version: int = BRAND_PROFILE_VERSION

    # --- Identity ---
    company_name: str = ""
    website: str = ""
    domain: str = ""

    # --- Existing content ---
    headline: str = ""
    ad_copy: str = ""

    # --- Visual identity ---
    colors: List[str] = field(default_factory=list)
    logo: Optional[BrandAsset] = None
    assets: List[BrandAsset] = field(default_factory=list)
    hero_assets: List[BrandAsset] = field(default_factory=list)
    hero_url: str = ""  # scraper's preferred hero candidate (provenance, not a BrandAsset)

    # --- Metadata / provenance ---
    source_metadata: Dict[str, Any] = field(default_factory=dict)
    screenshot_path: str = ""
    quality_score: float = 0.0
    vision_score: float = 0.0
    scraped_at: str = ""

    # --- Future business-intelligence fields (Sprint 2C+) ---
    # Kept with safe defaults; extraction NOT implemented in Sprint 2B.
    phone: str = ""
    location: str = ""
    service_area: str = ""
    services: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    differentiators: List[str] = field(default_factory=list)
    trust_signals: List[str] = field(default_factory=list)
    awards: List[str] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    guarantees: List[str] = field(default_factory=list)
    years_in_business: str = ""

    # --- Person-aware personalization (Sprint 5AB) ---
    # Source facts are evidence-backed; derived/generated copy lives separately.
    person_facts: PersonFacts = field(default_factory=PersonFacts)
    personalization_angle: str = ""
    personalization_basis: List[str] = field(default_factory=list)
    personalized_headline: str = ""
    personalized_cta: str = ""
    profile_summary: str = ""

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary for JSON output.

        Nested BrandAsset objects are serialized via their own to_dict().
        """
        return {
            "version": self.version,
            "company_name": self.company_name,
            "website": self.website,
            "domain": self.domain,
            "headline": self.headline,
            "ad_copy": self.ad_copy,
            "colors": list(self.colors),
            "logo": self.logo.to_dict() if self.logo else None,
            "assets": [a.to_dict() for a in self.assets],
            "hero_assets": [a.to_dict() for a in self.hero_assets],
            "hero_url": self.hero_url,
            "source_metadata": dict(self.source_metadata),
            "screenshot_path": self.screenshot_path,
            "quality_score": self.quality_score,
            "vision_score": self.vision_score,
            "scraped_at": self.scraped_at,
            # Future fields — serialized so they survive round-trips
            "phone": self.phone,
            "location": self.location,
            "service_area": self.service_area,
            "services": list(self.services),
            "categories": list(self.categories),
            "differentiators": list(self.differentiators),
            "trust_signals": list(self.trust_signals),
            "awards": list(self.awards),
            "certifications": list(self.certifications),
            "guarantees": list(self.guarantees),
            "years_in_business": self.years_in_business,
            "person_facts": self.person_facts.to_dict(),
            "personalization_angle": self.personalization_angle,
            "personalization_basis": list(self.personalization_basis),
            "personalized_headline": self.personalized_headline,
            "personalized_cta": self.personalized_cta,
            "profile_summary": self.profile_summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> BrandProfile:
        """Deserialize from a dictionary.

        - Unknown fields are silently ignored (forward-compatible).
        - Missing optional fields receive safe defaults.
        - Nested BrandAsset dicts are deserialized via BrandAsset.from_dict().
        """
        if not data:
            return cls()

        raw = dict(data)

        def _str(key: str, default: str = "") -> str:
            val = raw.get(key)
            return str(val) if val else default

        def _float(key: str, default: float = 0.0) -> float:
            try:
                return float(raw.get(key, default))
            except (TypeError, ValueError):
                return default

        def _list_str(key: str) -> List[str]:
            val = raw.get(key)
            if isinstance(val, list):
                return [str(v) for v in val]
            return []

        def _brand_asset(val: Any) -> Optional[BrandAsset]:
            if isinstance(val, dict) and val:
                try:
                    return BrandAsset.from_dict(val)
                except Exception:
                    return None
            return None

        def _brand_asset_list(val: Any) -> List[BrandAsset]:
            if isinstance(val, list):
                result: List[BrandAsset] = []
                for item in val:
                    asset = _brand_asset(item)
                    if asset is not None:
                        result.append(asset)
                return result
            return []

        def _meta(val: Any) -> Dict[str, Any]:
            if isinstance(val, dict):
                return dict(val)
            return {}

        return cls(
            version=int(raw.get("version", BRAND_PROFILE_VERSION)),
            company_name=_str("company_name"),
            website=_str("website"),
            domain=_str("domain"),
            headline=_str("headline"),
            ad_copy=_str("ad_copy"),
            colors=_list_str("colors"),
            logo=_brand_asset(raw.get("logo")),
            assets=_brand_asset_list(raw.get("assets")),
            hero_assets=_brand_asset_list(raw.get("hero_assets")),
            hero_url=_str("hero_url"),
            source_metadata=_meta(raw.get("source_metadata")),
            screenshot_path=_str("screenshot_path"),
            quality_score=_float("quality_score"),
            vision_score=_float("vision_score"),
            scraped_at=_str("scraped_at"),
            # Future fields
            phone=_str("phone"),
            location=_str("location"),
            service_area=_str("service_area"),
            services=_list_str("services"),
            categories=_list_str("categories"),
            differentiators=_list_str("differentiators"),
            trust_signals=_list_str("trust_signals"),
            awards=_list_str("awards"),
            certifications=_list_str("certifications"),
            guarantees=_list_str("guarantees"),
            years_in_business=_str("years_in_business"),
            person_facts=PersonFacts.from_dict(raw.get("person_facts")),
            personalization_angle=_str("personalization_angle"),
            personalization_basis=_list_str("personalization_basis"),
            personalized_headline=_str("personalized_headline"),
            personalized_cta=_str("personalized_cta"),
            profile_summary=_str("profile_summary"),
        )


# ---------------------------------------------------------------------------
# BrandProfileBuilder
# ---------------------------------------------------------------------------

class BrandProfileBuilder:
    """Builds a normalized BrandProfile from raw scraper output.

    Handles both NEW scraper output (structured BrandAsset dicts) and
    OLD scraper output (logo_path string, asset_paths list[str]).

    Usage::

        profile = BrandProfileBuilder.from_scrape_data(scraper_dict)
    """

    @staticmethod
    def from_scrape_data(data: Dict[str, Any]) -> BrandProfile:
        """Build a BrandProfile from a raw WebsiteScraper.run() dict.

        Maps scraper keys to BrandProfile fields. Handles both new
        structured BrandAsset data and legacy string-path fallbacks.
        """
        if not data:
            return BrandProfile()

        # --- Identity ---
        company = str(data.get("company") or "")
        url = str(data.get("url") or "")
        domain = BrandProfileBuilder._extract_domain(url)

        # --- Content ---
        headline = str(data.get("headline") or "")
        ad_copy = str(data.get("ad_copy") or "")

        # --- Colors ---
        brand_colors = data.get("brand_colors")
        if isinstance(brand_colors, list):
            colors = [str(c) for c in brand_colors]
        else:
            colors = []

        # --- Logo (structured BrandAsset preferred, legacy path fallback) ---
        logo: Optional[BrandAsset] = None
        logo_raw = data.get("logo")
        if isinstance(logo_raw, dict) and logo_raw:
            try:
                logo = BrandAsset.from_dict(logo_raw)
            except Exception:
                logo = None

        # --- Assets (structured list preferred) ---
        assets: List[BrandAsset] = []
        assets_raw = data.get("assets")
        if isinstance(assets_raw, list):
            for item in assets_raw:
                if isinstance(item, dict) and item:
                    try:
                        assets.append(BrandAsset.from_dict(item))
                    except Exception:
                        pass

        # --- Hero URL (always preserve as provenance) ---
        hero_url = str(data.get("hero_url") or "")

        # --- Hero assets (only when a matching normalized BrandAsset exists) ---
        hero_assets: List[BrandAsset] = []
        if hero_url:
            # Try to match hero_url to a normalized asset
            for asset in assets:
                if asset.source_url == hero_url:
                    hero_assets.append(asset)
                    break

        # --- Metadata / provenance ---
        meta_raw = data.get("metadata")
        source_metadata: Dict[str, Any] = (
            dict(meta_raw) if isinstance(meta_raw, dict) else {}
        )
        person_context_raw = data.get("person_context")
        person_context = dict(person_context_raw) if isinstance(person_context_raw, dict) else {}
        contact_name = str(person_context.get("contact_name") or "")
        if contact_name:
            source_metadata.setdefault("person_context", person_context)

        # --- Person-aware personalization (Sprint 5AB) ---
        personalization = choose_personalization(data)
        if personalization.person_facts.has_person_context():
            source_metadata.setdefault("person_facts", personalization.person_facts.to_dict())
            source_metadata.setdefault(
                "personalization",
                personalization.to_dict(),
            )

        asset_diagnostics = classify_brand_assets(
            assets,
            contact_name=contact_name,
            page_url=url,
            metadata=source_metadata,
        )
        if contact_name or asset_diagnostics.get("person_oriented"):
            source_metadata["asset_selection_diagnostics"] = asset_diagnostics

        # Preserve legacy paths in source_metadata for backward compatibility
        legacy_logo_path = str(data.get("logo_path") or "")
        legacy_asset_paths = data.get("asset_paths")
        if legacy_logo_path:
            source_metadata.setdefault("legacy_logo_path", legacy_logo_path)
        if isinstance(legacy_asset_paths, list) and legacy_asset_paths:
            source_metadata.setdefault(
                "legacy_asset_paths", [str(p) for p in legacy_asset_paths]
            )

        screenshot_path = str(
            data.get("screenshot_path")
            or data.get("screenshot_file")
            or ""
        )

        quality_score = 0.0
        try:
            quality_score = float(data.get("quality_score", 0) or 0)
        except (TypeError, ValueError):
            pass

        vision_score = 0.0
        try:
            vision_score = float(data.get("vision_score", 0) or 0)
        except (TypeError, ValueError):
            pass

        scraped_at = str(data.get("scraped_at") or "")

        # --- Business intelligence (Sprint 2C) ---
        bi = data.get("business_intel") or {}
        phone = str(bi.get("phone") or "")
        location = str(bi.get("location") or "")
        service_area = str(bi.get("service_area") or "")
        services = [str(s) for s in bi.get("services") or []]
        categories = [str(s) for s in bi.get("categories") or []]
        differentiators = [str(s) for s in bi.get("differentiators") or []]
        trust_signals = [str(s) for s in bi.get("trust_signals") or []]
        awards = [str(s) for s in bi.get("awards") or []]
        certifications = [str(s) for s in bi.get("certifications") or []]
        guarantees = [str(s) for s in bi.get("guarantees") or []]
        years_in_business = str(bi.get("years_in_business") or "")

        return BrandProfile(
            version=BRAND_PROFILE_VERSION,
            company_name=company,
            website=url,
            domain=domain,
            headline=headline,
            ad_copy=ad_copy,
            colors=colors,
            logo=logo,
            assets=assets,
            hero_assets=hero_assets,
            hero_url=hero_url,
            source_metadata=source_metadata,
            screenshot_path=screenshot_path,
            quality_score=quality_score,
            vision_score=vision_score,
            scraped_at=scraped_at,
            phone=phone,
            location=location,
            service_area=service_area,
            services=services,
            categories=categories,
            differentiators=differentiators,
            trust_signals=trust_signals,
            awards=awards,
            certifications=certifications,
            guarantees=guarantees,
            years_in_business=years_in_business,
            person_facts=personalization.person_facts,
            personalization_angle=personalization.personalization_angle,
            personalization_basis=personalization.personalization_basis,
            personalized_headline=personalization.headline,
            personalized_cta=personalization.cta,
            profile_summary=personalization.profile_summary,
        )

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract a clean domain from a URL string."""
        if not url:
            return ""
        try:
            parsed = urlparse(url)
            host = parsed.hostname or parsed.netloc or ""
            # Strip leading "www."
            if host.lower().startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return ""