"""Business intelligence extraction for BillboardAI.

Extracts structured business facts from scraped website content.
All extraction is evidence-based - no fabrication, no LLM calls,
no external APIs.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ======================================================================
# ExtractionContext
# ======================================================================

@dataclass
class ExtractionContext:
    """All available evidence for business-intelligence extraction."""
    soup: Optional[BeautifulSoup] = None
    html: str = ""
    url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    headline: str = ""
    company: str = ""

    _visible_text: Optional[str] = field(default=None, repr=False)
    _jsonld: Optional[List[Dict[str, Any]]] = field(default=None, repr=False)
    _tel_links: Optional[List[str]] = field(default=None, repr=False)
    _footer_text: Optional[str] = field(default=None, repr=False)
    _headings_text: Optional[str] = field(default=None, repr=False)
    _nav_text: Optional[str] = field(default=None, repr=False)

    @property
    def visible_text(self) -> str:
        if self._visible_text is None:
            self._visible_text = self.soup.get_text(" ", strip=True) if self.soup else ""
        return self._visible_text

    @property
    def jsonld(self) -> List[Dict[str, Any]]:
        if self._jsonld is None:
            self._jsonld = _extract_jsonld(self.soup)
        return self._jsonld

    @property
    def tel_links(self) -> List[str]:
        if self._tel_links is None:
            self._tel_links = _extract_tel_links(self.soup)
        return self._tel_links

    @property
    def footer_text(self) -> str:
        if self._footer_text is None:
            self._footer_text = _extract_footer_text(self.soup)
        return self._footer_text

    @property
    def headings_text(self) -> str:
        if self._headings_text is None:
            self._headings_text = _extract_headings_text(self.soup)
        return self._headings_text

    @property
    def nav_text(self) -> str:
        if self._nav_text is None:
            self._nav_text = _extract_nav_text(self.soup)
        return self._nav_text


def build_context(soup=None, html="", url="", metadata=None, headline="", company=""):
    return ExtractionContext(
        soup=soup, html=html, url=url,
        metadata=metadata or {}, headline=headline, company=company,
    )


# ======================================================================
# Internal helpers
# ======================================================================

def _extract_jsonld(soup):
    if not soup:
        return []
    results = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                results.append(data)
            elif isinstance(data, list):
                results.extend(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return results


def _extract_tel_links(soup):
    if not soup:
        return []
    results = []
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if href.lower().startswith("tel:"):
            number = href[4:].strip()
            if number:
                results.append(number)
    return results


def _extract_footer_text(soup):
    if not soup:
        return ""
    parts = []
    for tag in soup.find_all(["footer", "div"], class_=re.compile(r"footer", re.I)):
        parts.append(tag.get_text(" ", strip=True))
    for tag in soup.find_all("footer"):
        parts.append(tag.get_text(" ", strip=True))
    return " ".join(parts)


def _extract_headings_text(soup):
    if not soup:
        return ""
    parts = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = tag.get_text(" ", strip=True)
        if text:
            parts.append(text)
    return " | ".join(parts)


def _extract_nav_text(soup):
    if not soup:
        return ""
    parts = []
    for nav in soup.find_all("nav"):
        parts.append(nav.get_text(" ", strip=True))
    return " ".join(parts)


# ======================================================================
# JSON-LD helper
# ======================================================================

def _get_jsonld_value(ld, key):
    if key in ld:
        return ld[key]
    for v in ld.values():
        if isinstance(v, dict):
            result = _get_jsonld_value(v, key)
            if result:
                return result
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    result = _get_jsonld_value(item, key)
                    if result:
                        return result
    return None


# ======================================================================
# Phone extraction
# ======================================================================

_US_PHONE_RE = re.compile(
    r"(?:(?:\+?1[\s.\-]*)?\(?\d{3}\)?[\s.\-]*\d{3}[\s.\-]*\d{4})"
)
_FAX_RE = re.compile(r"\b(fax|facsimile)\b", re.IGNORECASE)
_ZIP_RE = re.compile(r"\b\d{5}(?:[-\s]\d{4})?\b")


def _normalize_phone(raw):
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
    return raw.strip()


def _is_fax_context(text, match_start, match_end):
    before = text[max(0, match_start - 30):match_start]
    after = text[match_end:match_end + 30]
    return bool(_FAX_RE.search(before) or _FAX_RE.search(after))


def _is_zip_code(text, match_start, match_end):
    matched = text[match_start:match_end]
    return bool(_ZIP_RE.fullmatch(matched.strip()))


def extract_phone(ctx):
    # 1. tel: links
    for raw in ctx.tel_links:
        m = _US_PHONE_RE.search(raw)
        if m:
            return _normalize_phone(m.group(0))
    # 2. JSON-LD telephone
    for ld in ctx.jsonld:
        phone = _get_jsonld_value(ld, "telephone")
        if phone:
            m = _US_PHONE_RE.search(str(phone))
            if m:
                return _normalize_phone(m.group(0))
    # 3. Footer text
    last_end = 0
    for m in _US_PHONE_RE.finditer(ctx.footer_text):
        between = ctx.footer_text[last_end:m.start()]
        if not _FAX_RE.search(between):
            if not _is_zip_code(ctx.footer_text, m.start(), m.end()):
                return _normalize_phone(m.group(0))
        last_end = m.end()
    # 4. General visible text
    last_end = 0
    for m in _US_PHONE_RE.finditer(ctx.visible_text):
        between = ctx.visible_text[last_end:m.start()]
        if not _FAX_RE.search(between):
            if not _is_zip_code(ctx.visible_text, m.start(), m.end()):
                return _normalize_phone(m.group(0))
        last_end = m.end()
    return ""


# ======================================================================
# Location extraction
# ======================================================================

_CITY_STATE_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s*,\s*"
    r"(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|"
    r"NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b"
)

_STATE_NAMES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
}

_CITY_FULLSTATE_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s*,\s*(" + "|".join(_STATE_NAMES) + r")\b"
)

_CITY_BLACKLIST = {
    "Serving", "Proudly", "Located", "Contact", "Welcome", "About",
    "Service", "Services", "Call", "Visit", "Our", "The", "Best",
    "Quality", "Professional", "Your", "Get", "Free", "We", "All",
    "New", "Top", "Local", "Trusted", "Family", "Residential",
    "Commercial", "Emergency", "Schedule", "Request", "Book",
}


def _extract_address_from_jsonld(ld):
    addr = _get_jsonld_value(ld, "address")
    if isinstance(addr, dict):
        parts = []
        street = addr.get("streetAddress", "")
        if street:
            parts.append(str(street))
        locality = addr.get("addressLocality", "")
        region = addr.get("addressRegion", "")
        if locality and region:
            parts.append(f"{locality}, {region}")
        elif locality:
            parts.append(str(locality))
        elif region:
            parts.append(str(region))
        if parts:
            return ", ".join(parts)
    if isinstance(addr, str) and addr.strip():
        return addr.strip()
    return None


def extract_location(ctx):
    # 1. JSON-LD postal address
    for ld in ctx.jsonld:
        addr = _extract_address_from_jsonld(ld)
        if addr:
            return addr
    # 2. Footer city/state
    m = _CITY_STATE_RE.search(ctx.footer_text)
    if m:
        return f"{m.group(1)}, {m.group(2)}"
    m = _CITY_FULLSTATE_RE.search(ctx.footer_text)
    if m:
        return f"{m.group(1)}, {m.group(2)}"
    # 3. Headings
    m = _CITY_STATE_RE.search(ctx.headings_text)
    if m:
        return f"{m.group(1)}, {m.group(2)}"
    m = _CITY_FULLSTATE_RE.search(ctx.headings_text)
    if m:
        return f"{m.group(1)}, {m.group(2)}"
    # 4. Visible text
    for m in _CITY_STATE_RE.finditer(ctx.visible_text):
        city = m.group(1)
        words = city.split()
        first_word = words[0]
        if first_word not in _CITY_BLACKLIST:
            return f"{city}, {m.group(2)}"
        # If first word is a blacklisted prefix (e.g. "Serving Houston"),
        # use the last word as the actual city
        if len(words) > 1:
            return f"{words[-1]}, {m.group(2)}"
    for m in _CITY_FULLSTATE_RE.finditer(ctx.visible_text):
        city = m.group(1)
        words = city.split()
        first_word = words[0]
        if first_word not in _CITY_BLACKLIST:
            return f"{city}, {m.group(2)}"
        if len(words) > 1:
            return f"{words[-1]}, {m.group(2)}"
    # 5. Metadata description
    desc = ctx.metadata.get("description", "")
    m = _CITY_STATE_RE.search(str(desc))
    if m:
        return f"{m.group(1)}, {m.group(2)}"
    return ""


# ======================================================================
# Service area extraction
# ======================================================================

# Geographic evidence: a capitalized place name (not a stopword) or a geo
# qualifier (Metro, County, Region, etc.). Service area must contain real
# geographic evidence, not just service-area vocabulary.
_GEO_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "at",
    "with", "by", "from", "up", "all", "any", "our", "your", "their",
    "surrounding", "greater", "area", "areas", "community", "metro",
    "region", "county", "valley", "serving", "proudly", "service", "services",
}
_GEO_QUALIFIERS = {
    "metro", "metroplex", "county", "region", "valley", "state",
    "statewide", "surrounding", "greater", "throughout",
}


def _has_geo_evidence(geo):
    words = geo.split()
    if not words:
        return False
    # Any geo qualifier present alongside a place word
    if any(w.lower() in _GEO_QUALIFIERS for w in words) and any(
        w[0].isupper() for w in words
    ):
        return True
    # A capitalized word that is a likely place name
    for w in words:
        if w[0].isupper() and w.lower() not in _GEO_STOPWORDS:
            return True
    return False


_SERVICE_AREA_PATTERNS = [
    # "Serving Sioux Falls and surrounding areas" -> capture "Sioux Falls"
    re.compile(r"(?:Serving|Proudly\s+serving)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s*,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)*)\s+and\s+surrounding\s+areas?", re.I),
    # "Proudly serving Greater Sioux Falls" -> capture "Greater Sioux Falls"
    re.compile(r"(?:Serving|Proudly\s+serving)\s+(Greater\s+[A-Z][a-z]+(?:\s+(?!serving|proudly|and)[A-Z][a-z]+){0,2})", re.I),
    # "Serving Sioux Falls, Brandon, and Harrisburg" -> capture multi-city
    re.compile(r"(?:Serving|Proudly\s+serving)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:\s*,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)*)", re.I),
    # "Serving southeastern South Dakota" -> capture "southeastern South Dakota"
    re.compile(r"(?:Serving|Proudly\s+serving)\s+(southeastern|southwestern|northeastern|northwestern|eastern|western|northern|southern|central|statewide|throughout)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.I),
    # "Serving the Denver Metro area" -> capture "Denver Metro"
    re.compile(r"(?:Serving|Proudly\s+serving)\s+the\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:Metro|Metro\s+Area|Area|Region)\b", re.I),
    # "Serving the Dallas-Fort Worth area" -> capture "Dallas-Fort Worth"
    re.compile(r"(?:Serving|Proudly\s+serving)\s+the\s+([A-Z][a-z]+(?:[-–]\s*[A-Z][a-z]+)?(?:\s+[A-Z][a-z]+)?)\s+(?:area|metro|region|county)\b", re.I),
]

# Standalone geo patterns (no "serving" prefix), requiring a capitalized place.
_GEO_PATTERNS = [
    # "Service area: Denver Metro" -> capture "Denver Metro"
    re.compile(r"service\s+area\s*:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(Metro|Metroplex|Metro\s+Area|Area|Region|County)\b", re.I),
    # "Denver Metro" / "Dallas-Fort Worth Metroplex" -> capture "Denver Metro"
    re.compile(r"\b([A-Z][a-z]+(?:[-–]\s*[A-Z][a-z]+)?(?:\s+[A-Z][a-z]+)?)\s+(Metro|Metroplex|Metro\s+Area|County|Region)\b"),
    # "Greater Sioux Falls"
    re.compile(r"\b(Greater\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"),
]


def extract_service_area(ctx):
    text = f"{ctx.footer_text} {ctx.headings_text} {ctx.visible_text}"
    # 1. Explicit "Serving X" patterns capturing the geographic phrase
    for pat in _SERVICE_AREA_PATTERNS:
        m = pat.search(text)
        if m:
            geo = " ".join(g for g in m.groups() if g).strip()
            if _has_geo_evidence(geo):
                return geo
    # 2. Standalone geo patterns (e.g. "Service area: Denver Metro")
    for pat in _GEO_PATTERNS:
        m = pat.search(text)
        if m:
            geo = " ".join(g for g in m.groups() if g).strip()
            if _has_geo_evidence(geo):
                return geo
    return ""


# ======================================================================
# Services extraction
# ======================================================================

# High-confidence multi-word service phrases (matched anywhere in the page).
_SERVICE_PHRASES = [
    "residential roofing", "commercial roofing", "roof replacement",
    "roof repair", "roof installation", "roof inspection",
    "roof maintenance", "roof restoration", "metal roofing",
    "flat roofing", "emergency roof repair", "storm damage repair",
    "siding installation", "siding repair", "gutter installation",
    "gutter repair", "gutter cleaning", "seamless gutters",
    "window installation", "window replacement", "door installation",
    "door replacement", "attic insulation", "spray foam insulation",
    "deck building", "deck repair", "fence installation",
    "chimney repair", "solar panel installation", "exterior painting",
    "home improvement", "general contractor", "air conditioning",
    "furnace repair", "ac repair", "water heater", "drain cleaning",
    "lawn care", "tree service", "home inspection",
    "water damage restoration", "fire damage restoration",
    "mold remediation", "appliance repair", "garage door",
    "foundation repair", "basement waterproofing", "basement finishing",
    "room addition", "general dentistry", "cosmetic dentistry",
    "teeth whitening", "dental implants", "primary care", "urgent care",
    "family medicine", "physical therapy", "auto repair", "oil change",
    "brake repair", "collision repair", "auto body", "car wash",
    "bookkeeping", "tax preparation", "real estate", "financial planning",
    "web design", "web development", "computer repair", "software development",
    "pet grooming", "dog walking", "event planning", "personal training",
    "carpet cleaning", "pressure washing", "window cleaning",
    "junk removal", "dumpster rental", "bathroom remodeling",
    "kitchen remodeling", "whole home remodeling", "new construction",
    "commercial construction", "interior design", "pest control",
    "termite inspection", "radon testing", "energy audit",
    "asbestos abatement", "hvac repair", "plumbing repair",
    "electrical repair", "roofing contractor", "landscaping services",
    "tree trimming", "lawn mowing", "snow removal", "welding services",
    "concrete work", "drywall repair", "tiling services",
    "flooring installation", "painting services", "cabinet installation",
    "countertop installation", "fencing services", "deck construction",
    "porch building", "patio installation", "retaining walls",
    "driveway paving", "sealcoating", "power washing", "soft washing",
    "exterior house cleaning", "interior house cleaning", "move out cleaning",
    "office cleaning", "deep cleaning", "air duct cleaning",
    "dryer vent cleaning", "gutter guard installation", "leaf guard",
    "roof coating", "roof sealing", "roof leak repair", "flat roof repair",
]

# Unambiguous service nouns. Only trusted in service context (nav/headings/footer),
# never as a standalone from general body text.
_SINGLE_WORD_SERVICES = {
    "siding", "gutters", "windows", "doors", "roofing", "plumbing",
    "electrical", "hvac", "painting", "flooring", "concrete", "masonry",
    "insulation", "remodeling", "construction", "welding", "excavation",
    "landscaping", "demolition", "surveying", "dentistry", "orthodontics",
    "chiropractic", "massage", "photography", "videography", "catering",
    "florist", "tutoring", "accounting", "insurance", "storage", "towing",
    "locksmith", "fencing", "framing", "tiling", "drywall", "carpentry",
    "roofing", "electrical", "plumbing", "hvac", "gutters", "siding",
}


def extract_services(ctx):
    # Multi-word specific phrases: match anywhere in the page.
    phrase_text = f"{ctx.nav_text} {ctx.headings_text} {ctx.footer_text} {ctx.visible_text}"
    found = set()
    for name in _SERVICE_PHRASES:
        if re.search(r"\b" + re.escape(name) + r"\b", phrase_text, re.I):
            found.add(name)
    # Single-word services: only trusted in service context (nav/headings/footer).
    service_context = f"{ctx.nav_text} {ctx.headings_text} {ctx.footer_text}"
    for name in _SINGLE_WORD_SERVICES:
        if re.search(r"\b" + re.escape(name) + r"\b", service_context, re.I):
            found.add(name)
    return sorted(found)


# ======================================================================
# Categories extraction
# ======================================================================

_CATEGORY_RULES = [
    (["roofing", "roof", "roofer", "roofers"], "roofing"),
    (["contractor", "contracting", "general contractor", "construction"], "contractor"),
    (["dentist", "dentistry", "dental", "orthodont"], "dentist"),
    (["realtor", "real estate", "realty", "broker"], "realtor"),
    (["plumb", "plumber", "plumbing"], "plumber"),
    (["electric", "electrical", "electrician"], "electrician"),
    (["hvac", "heating", "air conditioning", "furnace"], "hvac"),
    (["landscap", "lawn", "yard", "garden"], "landscaping"),
    (["paint", "painter", "painting"], "painting"),
    (["clean", "cleaning", "janitorial", "maid"], "cleaning"),
    (["mov", "mover", "moving", "relocation"], "moving"),
    (["auto repair", "mechanic", "automotive", "car repair"], "auto repair"),
    (["law", "legal", "attorney", "lawyer"], "legal"),
    (["medical", "clinic", "physician", "doctor", "healthcare"], "medical"),
    (["salon", "barber", "hair", "beauty", "spa"], "salon"),
    (["restaurant", "cafe", "diner", "eatery", "pizza"], "restaurant"),
    (["retail", "store", "shop", "boutique"], "retail"),
    (["fitness", "gym", "workout", "crossfit", "yoga"], "fitness"),
    (["photograph", "photographer", "photo"], "photography"),
    (["account", "accounting", "cpa", "tax", "bookkeeping"], "accounting"),
    (["insurance", "insure", "agency"], "insurance"),
    (["childcare", "daycare", "preschool", "nursery"], "childcare"),
    (["pet", "dog", "cat", "veterinar", "grooming"], "pet care"),
    (["tutor", "tutoring", "education", "learning center"], "tutoring"),
    (["it service", "computer repair", "tech support", "managed it"], "it services"),
    (["market", "advertising", "seo", "social media", "branding"], "marketing"),
    (["event", "wedding", "catering", "venue"], "event"),
    (["transport", "logistics", "trucking", "freight", "delivery"], "transportation"),
    (["manufactur", "fabrication", "production", "industrial"], "manufacturing"),
    (["wholesale", "distribut", "supply"], "wholesale"),
    (["nonprofit", "non-profit", "charity", "foundation"], "nonprofit"),
    (["school", "college", "university", "academy"], "education"),
    (["church", "ministry", "temple", "mosque", "synagogue"], "religious"),
    (["hotel", "motel", "inn", "lodging", "resort"], "lodging"),
    (["storage", "warehouse", "self storage"], "storage"),
    (["security", "alarm", "surveillance", "locksmith"], "security"),
    (["flooring", "carpet", "hardwood", "tile"], "flooring"),
    (["concrete", "cement", "foundation", "driveway"], "concrete"),
    (["pest", "exterminat", "termite", "rodent"], "pest control"),
    (["tree", "arborist", "stump", "trimming"], "tree service"),
    (["waste", "junk", "dumpster", "garbage"], "waste"),
    (["pressure wash", "power wash", "soft wash"], "pressure washing"),
    (["handyman", "handy man", "home repair"], "handyman"),
    (["appliance", "refrigerator", "washer", "dryer"], "appliance repair"),
    (["glass", "window tint", "windshield", "glazing"], "glass"),
    (["weld", "welding", "fabrication"], "welding"),
    (["excavat", "grading", "trenching", "earthwork"], "excavation"),
    (["survey", "surveying", "land survey"], "surveying"),
    (["engineer", "engineering", "structural"], "engineering"),
    (["architect", "architecture", "design build"], "architecture"),
    (["interior design", "interior decorat"], "interior design"),
    (["property management", "property manager"], "property management"),
    (["financial", "wealth", "investment", "retirement"], "financial"),
    (["mortgage", "lending", "loan", "refinance"], "mortgage"),
    (["staffing", "recruiting", "temporary", "employment"], "staffing"),
    (["print", "printing", "sign", "banner"], "printing"),
    (["funeral", "cremation", "mortuary", "cemetery"], "funeral"),
    (["pharmacy", "pharmacist", "drug", "prescription"], "pharmacy"),
    (["optometr", "eye", "vision", "glasses"], "optometry"),
    (["chiropract", "spinal", "adjustment"], "chiropractic"),
    (["physical therap", "physiotherapy", "rehab"], "physical therapy"),
    (["counsel", "therapy", "psycholog", "psychiatr"], "mental health"),
    (["home health", "home care", "caregiver", "senior care"], "home health"),
    (["assisted living", "nursing home", "retirement community"], "assisted living"),
    (["urgent care", "walk-in clinic", "immediate care"], "urgent care"),
    (["dermatolog", "skin", "acne"], "dermatology"),
    (["cosmetic", "plastic surgery", "botox"], "cosmetic"),
    (["weight loss", "diet", "nutrition"], "weight loss"),
    (["hearing", "audiology", "hearing aid"], "hearing"),
    (["podiatr", "foot", "ankle"], "podiatry"),
    (["acupuncture", "acupuncturist"], "acupuncture"),
    (["massage", "massage therapy", "bodywork"], "massage"),
    (["tow", "towing", "roadside", "wrecker"], "towing"),
    (["car wash", "auto detail", "detailing"], "car wash"),
    (["tire", "wheel", "alignment", "brake"], "tire"),
    (["body shop", "collision", "auto body"], "body shop"),
    (["oil change", "lube", "quick lube"], "oil change"),
    (["transmission", "transmission repair"], "transmission"),
    (["muffler", "exhaust"], "muffler"),
    (["car rental", "rental car", "auto rental"], "car rental"),
    (["limo", "limousine", "chauffeur"], "limousine"),
    (["taxi", "cab", "rideshare"], "taxi"),
    (["bus", "charter", "shuttle", "motorcoach"], "bus"),
    (["airport", "airport shuttle", "airport transfer"], "airport service"),
    (["courier", "messenger", "same day delivery"], "courier"),
    (["freight", "cargo", "shipping", "logistics"], "freight"),
    (["warehous", "fulfillment", "distribution center"], "warehouse"),
    (["packaging", "packing", "crating"], "packaging"),
    (["notary", "notarize", "notary public"], "notary"),
    (["translat", "interpret", "language service"], "translation"),
    (["virtual assistant", "va service", "remote assistant"], "virtual assistant"),
    (["call center", "contact center", "answering service"], "call center"),
    (["data entry", "data processing", "transcription"], "data entry"),
    (["web design", "web development"], "web design"),
    (["software", "app development", "saas", "programming"], "software"),
    (["hosting", "domain", "web host", "cloud"], "hosting"),
    (["seo", "search engine", "google ads", "ppc"], "seo"),
    (["social media", "facebook ads", "instagram"], "social media"),
    (["content", "copywriting", "blog", "ghostwriting"], "content"),
    (["video", "videography", "film", "production"], "video"),
    (["audio", "podcast", "sound", "music production"], "audio"),
    (["animation", "motion graphics", "3d", "vfx"], "animation"),
    (["game", "gaming", "esports"], "game"),
    (["drone", "aerial", "uav"], "drone"),
    (["inspect", "home inspection", "building inspection"], "inspection"),
    (["apprais", "valuation", "assessment"], "appraisal"),
    (["home staging", "staging", "interior redesign"], "home staging"),
    (["organiz", "declutter", "professional organizer"], "organizing"),
    (["carpet clean", "upholstery", "steam clean"], "carpet cleaning"),
    (["water damage", "flood", "mold", "restoration"], "water damage"),
    (["fire damage", "smoke damage", "fire restoration"], "fire damage"),
    (["biohazard", "crime scene", "trauma"], "biohazard"),
    (["asbestos", "abatement", "lead paint"], "asbestos"),
    (["radon", "radon testing", "radon mitigation"], "radon"),
    (["energy", "solar", "renewable"], "energy"),
    (["ev", "electric vehicle", "ev charger"], "electric vehicle"),
    (["generator", "backup power", "standby generator"], "generator"),
    (["satellite", "dish", "directv", "starlink"], "satellite"),
    (["cable", "fiber", "broadband", "internet provider"], "cable"),
    (["telecom", "voip", "phone system"], "telecom"),
    (["office", "coworking", "executive suite"], "office"),
    (["franchise", "franchising", "business opportunity"], "franchise"),
    (["consult", "advisory", "strategy"], "consulting"),
    (["coach", "mentoring", "life coach"], "coaching"),
    (["training", "workshop", "seminar", "certification"], "training"),
    (["publish", "book", "magazine", "journal"], "publishing"),
    (["music", "band", "orchestra", "choir"], "music"),
    (["art", "gallery", "museum", "exhibit"], "art"),
    (["theater", "theatre", "performing arts"], "theater"),
    (["dance", "ballet", "choreography"], "dance"),
    (["museum", "exhibit", "collection"], "museum"),
    (["library", "archive", "public library"], "library"),
    (["park", "recreation", "playground", "trail"], "park"),
    (["zoo", "aquarium", "wildlife", "safari"], "zoo"),
    (["golf", "country club", "golf course"], "golf"),
    (["sport", "athletic", "stadium", "arena"], "sports"),
    (["camp", "summer camp", "day camp"], "camp"),
    (["marina", "boat", "yacht", "sailing"], "marina"),
    (["fishing", "charter", "guide", "outfitter"], "fishing"),
    (["hunting", "outfitter", "game preserve"], "hunting"),
    (["ski", "snowboard", "ski resort"], "ski"),
    (["scuba", "diving", "snorkel"], "scuba"),
    (["skydiving", "parachute", "tandem jump"], "skydiving"),
    (["rafting", "kayaking", "canoeing"], "rafting"),
    (["zip line", "zipline", "canopy tour"], "zip line"),
    (["escape room", "puzzle room", "mystery room"], "escape room"),
    (["axe throwing", "hatchet", "throwing range"], "axe throwing"),
    (["brewery", "brewpub", "craft beer"], "brewery"),
    (["winery", "vineyard", "wine tasting"], "winery"),
    (["distill", "spirits", "whiskey", "vodka"], "distillery"),
    (["coffee", "cafe", "espresso", "roaster"], "coffee"),
    (["bakery", "bake", "pastry", "bread"], "bakery"),
    (["catering", "caterer", "banquet"], "catering"),
    (["food truck", "mobile food", "food cart"], "food truck"),
    (["meal prep", "meal delivery", "prepared meal"], "meal prep"),
    (["grocery", "supermarket", "market"], "grocery"),
    (["liquor", "wine shop", "beer store"], "liquor"),
    (["convenience store", "gas station", "c-store"], "convenience"),
    (["florist", "flower", "bouquet"], "florist"),
    (["jewelry", "jeweler", "diamond", "watch"], "jewelry"),
    (["clothing", "apparel", "fashion", "boutique"], "clothing"),
    (["shoe", "footwear", "sneaker", "boot"], "shoes"),
    (["sporting goods", "sports equipment", "outdoor gear"], "sporting goods"),
    (["bicycle", "bike", "cycling", "ebike"], "bicycle"),
    (["motorcycle", "motorbike", "harley"], "motorcycle"),
    (["boat dealer", "marine dealer", "boat sales"], "boat dealer"),
    (["rv", "motorhome", "camper", "travel trailer"], "rv"),
    (["furniture", "mattress", "sofa", "bedroom"], "furniture"),
    (["appliance", "refrigerator", "washer", "dryer"], "appliance"),
    (["electronics", "computer", "laptop", "phone"], "electronics"),
    (["hardware", "tools", "lumber", "building supply"], "hardware"),
    (["paint store", "paint supply", "sherwin"], "paint store"),
    (["nursery", "garden center", "greenhouse"], "nursery"),
    (["pet store", "pet supply", "aquarium"], "pet store"),
    (["bookstore", "book shop", "comic"], "bookstore"),
    (["music store", "instrument", "guitar", "piano"], "music store"),
    (["hobby", "craft", "model", "rc"], "hobby"),
    (["antique", "vintage", "collectible"], "antique"),
    (["thrift", "second hand", "charity shop"], "thrift"),
    (["pawn", "pawnbroker", "gold buyer"], "pawn"),
    (["auction", "auctioneer", "estate sale"], "auction"),
    (["rental", "equipment rental", "tool rental"], "rental"),
    (["leasing", "lease", "equipment leasing"], "leasing"),
    (["lending", "loan", "credit union", "mortgage"], "financing"),
    (["bank", "credit union", "savings", "checking"], "banking"),
    (["investment", "brokerage", "wealth management"], "investment"),
    (["tax", "irs", "tax preparation", "tax resolution"], "tax"),
    (["payroll", "payroll service", "hr", "human resources"], "payroll"),
    (["bookkeeping", "quickbooks", "accounting"], "bookkeeping"),
    (["audit", "auditing", "internal audit"], "audit"),
    (["business service", "b2b"], "business services"),
    (["printing", "print shop", "copy", "blueprint"], "printing"),
    (["shipping", "mailbox", "pack and ship"], "shipping"),
    (["office supply", "stationery", "paper"], "office supply"),
    (["shred", "document destruction"], "document shredding"),
    (["records management", "document storage"], "records management"),
    (["background check", "screening", "drug test"], "background check"),
    (["private investigat", "detective"], "private investigation"),
    (["process server", "process serving"], "process server"),
    (["court report", "stenographer", "deposition"], "court reporting"),
    (["legal document", "paralegal"], "legal document"),
    (["mediation", "arbitration", "dispute resolution"], "mediation"),
    (["bail bond", "bail bondsman"], "bail bonds"),
    (["process serving", "service of process"], "process serving"),
]


def extract_categories(ctx):
    # STRONG business identity only: company name, metadata title, H1, and
    # meaningful JSON-LD business types. Marketing headings (h2-h4) and body
    # copy are NOT used, so incidental words (energy, office, legal, etc.)
    # cannot classify a business. Services provide repeated high-confidence
    # trade evidence. Financing/capabilities are not categories.
    identity_parts = [
        str(ctx.metadata.get("title") or ""),
        ctx.company,
    ]
    # H1 (main title heading) is authoritative business identity.
    if ctx.soup is not None:
        h1 = " ".join(
            t.get_text(" ", strip=True) for t in ctx.soup.find_all("h1")
        )
        if h1:
            identity_parts.append(h1)
    # JSON-LD @type — only meaningful business types, exclude generic schema types.
    _GENERIC_SCHEMA_TYPES = {
        "website", "organization", "service", "webpage", "itemlist",
        "imageobject", "breadcrumblist", "faqpage", "thing", "creativework",
        "product", "offer", "place", "localbusiness", "homeandconstructionbusiness",
        "professional_service", "generalcontractor",
    }
    for ld in ctx.jsonld:
        t = ld.get("@type")
        if isinstance(t, str):
            if t.lower() not in _GENERIC_SCHEMA_TYPES:
                identity_parts.append(t)
        elif isinstance(t, list):
            for x in t:
                if str(x).lower() not in _GENERIC_SCHEMA_TYPES:
                    identity_parts.append(str(x))
    identity = " ".join(identity_parts).lower()
    # Services provide repeated high-confidence evidence for category.
    services = " ".join(extract_services(ctx)).lower()

    combined = f"{identity} {services}"
    found = []
    for keywords, category in _CATEGORY_RULES:
        for kw in keywords:
            # Word-boundary prefix match avoids substring false positives
            # (e.g. "law" in "flawless", "ev" in "Elevating", "rv" in "services").
            if re.search(r"\b" + re.escape(kw), combined):
                found.append(category)
                break
    # Deduplicate preserving order
    seen = set()
    result = []
    for c in found:
        if c not in seen:
            seen.add(c)
            result.append(c)
    # Trade-based categories imply "contractor" (roofing, plumbing, etc.)
    _TRADE_CATEGORIES = {
        "roofing", "plumber", "electrician", "hvac", "painting",
        "flooring", "concrete", "landscaping", "handyman", "welding",
        "excavation", "glass", "masonry", "tiling", "drywall",
    }
    if "contractor" not in result and any(c in _TRADE_CATEGORIES for c in result):
        result.append("contractor")
    return result


# ======================================================================
# Differentiators extraction
# ======================================================================

_DIFFERENTIATOR_PATTERNS = [
    ("locally owned", re.compile(r"\blocally\s+owned\b", re.I)),
    ("family owned", re.compile(r"\bfamily\s+owned\b", re.I)),
    ("family owned and operated", re.compile(r"\bfamily\s+owned\s+(?:and|&)\s+operated\b", re.I)),
    ("free estimates", re.compile(r"\bfree\s+estimates?\b", re.I)),
    ("free inspection", re.compile(r"\bfree\s+inspections?\b", re.I)),
    ("free consultation", re.compile(r"\bfree\s+consultations?\b", re.I)),
    ("financing available", re.compile(r"\bfinancing\s+available\b", re.I)),
    ("same-day service", re.compile(r"\bsame[\s-]day\s+service\b", re.I)),
    ("24/7 emergency service", re.compile(r"\b24\s*/\s*7\s+emergency\b", re.I)),
    ("emergency service", re.compile(r"\bemergency\s+service\b", re.I)),
    ("no subcontractors", re.compile(r"\bno\s+subcontractors\b", re.I)),
    ("veteran owned", re.compile(r"\bveteran\s+owned\b", re.I)),
    ("woman owned", re.compile(r"\bwoman[\s-]owned\b", re.I)),
    ("minority owned", re.compile(r"\bminority\s+owned\b", re.I)),
    ("locally operated", re.compile(r"\blocally\s+operated\b", re.I)),
    ("upfront pricing", re.compile(r"\bup[\s-]?front\s+pricing\b", re.I)),
    ("no hidden fees", re.compile(r"\bno\s+hidden\s+fees?\b", re.I)),
    ("price match guarantee", re.compile(r"\bprice\s+match\s+guarantee\b", re.I)),
    ("on-time guarantee", re.compile(r"\bon[\s-]time\s+guarantee\b", re.I)),
    ("customer focused", re.compile(r"\bcustomer[\s-]focused\b", re.I)),
    ("eco-friendly", re.compile(r"\beco[\s-]friendly\b", re.I)),
    ("green business", re.compile(r"\bgreen\s+business\b", re.I)),
    ("energy efficient", re.compile(r"\benergy[\s-]efficient\b", re.I)),
    ("sustainable", re.compile(r"\bsustainable\b", re.I)),
    ("family-run", re.compile(r"\bfamily[\s-]run\b", re.I)),
    ("multi-generational", re.compile(r"\bmulti[\s-]generational\b", re.I)),
    ("second generation", re.compile(r"\bsecond[\s-]generation\b", re.I)),
    ("third generation", re.compile(r"\bthird[\s-]generation\b", re.I)),
    ("fourth generation", re.compile(r"\bfourth[\s-]generation\b", re.I)),
    ("fast response", re.compile(r"\bfast\s+response\b", re.I)),
    ("rapid response", re.compile(r"\brapid\s+response\b", re.I)),
    ("quick turnaround", re.compile(r"\bquick\s+turnaround\b", re.I)),
    ("next-day installation", re.compile(r"\bnext[\s-]day\s+installation\b", re.I)),
    ("weekend availability", re.compile(r"\bweekend\s+availability\b", re.I)),
    ("evening appointments", re.compile(r"\bevening\s+appointments?\b", re.I)),
    ("walk-ins welcome", re.compile(r"\bwalk[\s-]ins?\s+welcome\b", re.I)),
    ("no appointment needed", re.compile(r"\bno\s+appointment\s+needed\b", re.I)),
    ("mobile service", re.compile(r"\bmobile\s+service\b", re.I)),
    ("we come to you", re.compile(r"\bwe\s+come\s+to\s+you\b", re.I)),
    ("on-site service", re.compile(r"\bon[\s-]site\s+service\b", re.I)),
    ("free pickup and delivery", re.compile(r"\bfree\s+pickup\s+(?:and|&)\s+delivery\b", re.I)),
    ("curbside pickup", re.compile(r"\bcurbside\s+pickup\b", re.I)),
    ("contactless service", re.compile(r"\bcontactless\s+service\b", re.I)),
    ("virtual consultations", re.compile(r"\bvirtual\s+consultations?\b", re.I)),
    ("online booking", re.compile(r"\bonline\s+booking\b", re.I)),
    ("easy scheduling", re.compile(r"\beasy\s+scheduling\b", re.I)),
    ("flexible scheduling", re.compile(r"\bflexible\s+scheduling\b", re.I)),
    ("custom solutions", re.compile(r"\bcustom\s+solutions?\b", re.I)),
    ("tailored solutions", re.compile(r"\btailored\s+solutions?\b", re.I)),
    ("personalized service", re.compile(r"\bpersonalized\s+service\b", re.I)),
    ("one-stop shop", re.compile(r"\bone[\s-]stop[\s-]shop\b", re.I)),
    ("full-service", re.compile(r"\bfull[\s-]service\b", re.I)),
    ("turnkey solutions", re.compile(r"\bturnkey\s+solutions?\b", re.I)),
    ("hassle-free", re.compile(r"\bhassle[\s-]free\b", re.I)),
    ("stress-free", re.compile(r"\bstress[\s-]free\b", re.I)),
    ("worry-free", re.compile(r"\bworry[\s-]free\b", re.I)),
    ("risk-free", re.compile(r"\brisk[\s-]free\b", re.I)),
    ("no obligation", re.compile(r"\bno\s+obligation\b", re.I)),
    ("no pressure", re.compile(r"\bno\s+pressure\b", re.I)),
    ("transparent pricing", re.compile(r"\btransparent\s+pricing\b", re.I)),
    ("honest pricing", re.compile(r"\bhonest\s+pricing\b", re.I)),
    ("fair pricing", re.compile(r"\bfair\s+pricing\b", re.I)),
    ("competitive pricing", re.compile(r"\bcompetitive\s+pricing\b", re.I)),
    ("affordable rates", re.compile(r"\baffordable\s+rates?\b", re.I)),
    ("budget-friendly", re.compile(r"\bbudget[\s-]friendly\b", re.I)),
    ("discounts available", re.compile(r"\bdiscounts?\s+available\b", re.I)),
    ("senior discounts", re.compile(r"\bsenior\s+discounts?\b", re.I)),
    ("military discounts", re.compile(r"\bmilitary\s+discounts?\b", re.I)),
    ("first responder discount", re.compile(r"\bfirst\s+responder\s+discount\b", re.I)),
    ("referral program", re.compile(r"\breferral\s+program\b", re.I)),
    ("loyalty program", re.compile(r"\bloyalty\s+program\b", re.I)),
    ("membership benefits", re.compile(r"\bmembership\s+benefits?\b", re.I)),
    ("free shipping", re.compile(r"\bfree\s+shipping\b", re.I)),
    ("free delivery", re.compile(r"\bfree\s+delivery\b", re.I)),
    ("free returns", re.compile(r"\bfree\s+returns?\b", re.I)),
    ("money-back guarantee", re.compile(r"\bmoney[\s-]back\s+guarantee\b", re.I)),
    ("100% satisfaction", re.compile(r"\b100%?\s+satisfaction\b", re.I)),
    ("no-surprise guarantee", re.compile(r"\bno[\s-]surprise\s+guarantee\b", re.I)),
    ("done right guarantee", re.compile(r"\bdone\s+right\s+guarantee\b", re.I)),
    ("clean guarantee", re.compile(r"\bclean\s+guarantee\b", re.I)),
    ("lowest price guarantee", re.compile(r"\blowest\s+price\s+guarantee\b", re.I)),
]


def extract_differentiators(ctx):
    text = f"{ctx.footer_text} {ctx.headings_text} {ctx.visible_text}"
    found = set()
    for name, pat in _DIFFERENTIATOR_PATTERNS:
        if pat.search(text):
            found.add(name)
    return sorted(found)


# ======================================================================
# Trust signals extraction
# ======================================================================

_TRUST_SIGNAL_PATTERNS = [
    ("licensed", re.compile(r"\blicensed\b", re.I)),
    ("insured", re.compile(r"\binsured\b", re.I)),
    ("bonded", re.compile(r"\bbonded\b", re.I)),
    ("BBB accredited", re.compile(r"\bBBB\s+[Aa]ccredited\b", re.I)),
    ("BBB A+", re.compile(r"\bBBB\s+A\+", re.I)),
    ("Google rating", re.compile(r"\bGoogle\s+rating\b", re.I)),
    ("5-star", re.compile(r"\b5[\s-]star\b", re.I)),
    ("star rating", re.compile(r"\b\d+(?:\.\d+)?\s+stars?\b", re.I)),
    ("award-winning", re.compile(r"\baward[\s-]winning\b", re.I)),
    ("years of experience", re.compile(r"\byears?\s+of\s+experience\b", re.I)),
    ("manufacturer certified", re.compile(r"\bmanufacturer[\s-]certified\b", re.I)),
    ("factory certified", re.compile(r"\bfactory[\s-]certified\b", re.I)),
    ("OSHA certified", re.compile(r"\bOSHA\s+certified\b", re.I)),
    ("EPA certified", re.compile(r"\bEPA\s+certified\b", re.I)),
    ("Chamber of Commerce", re.compile(r"\bChamber\s+of\s+Commerce\b", re.I)),
    ("Google Guaranteed", re.compile(r"\bGoogle\s+Guaranteed\b", re.I)),
    ("Google Screened", re.compile(r"\bGoogle\s+Screened\b", re.I)),
    ("workers comp", re.compile(r"\bworkers?'?\s*comp\b", re.I)),
    ("background checked", re.compile(r"\bbackground[\s-]checked\b", re.I)),
    ("drug tested", re.compile(r"\bdrug[\s-]tested\b", re.I)),
    ("LEED certified", re.compile(r"\bLEED\s+[Cc]ertified\b", re.I)),
    ("Energy Star certified", re.compile(r"\bEnergy\s+Star\s+[Cc]ertified\b", re.I)),
    ("B Corp certified", re.compile(r"\bB\s+Corp\s+[Cc]ertified\b", re.I)),
    ("MBE certified", re.compile(r"\bMBE\s+[Cc]ertified\b", re.I)),
    ("WBE certified", re.compile(r"\bWBE\s+[Cc]ertified\b", re.I)),
    ("DBE certified", re.compile(r"\bDBE\s+[Cc]ertified\b", re.I)),
    ("SBA certified", re.compile(r"\bSBA\s+[Cc]ertified\b", re.I)),
    ("VOSB certified", re.compile(r"\bVOSB\s+[Cc]ertified\b", re.I)),
    ("SDVOSB certified", re.compile(r"\bSDVOSB\s+[Cc]ertified\b", re.I)),
    ("HUBZone certified", re.compile(r"\bHUBZone\s+[Cc]ertified\b", re.I)),
    ("8(a) certified", re.compile(r"\b8\s*\(a\)\s+[Cc]ertified\b", re.I)),
    ("NRCA member", re.compile(r"\bNRCA\s+member\b", re.I)),
    ("GAF certified", re.compile(r"\bGAF\s+[Cc]ertified\b", re.I)),
    ("Owens Corning certified", re.compile(r"\bOwens\s+Corning\s+[Cc]ertified\b", re.I)),
    ("CertainTeed certified", re.compile(r"\bCertainTeed\s+[Cc]ertified\b", re.I)),
    ("Malarkey certified", re.compile(r"\bMalarkey\s+[Cc]ertified\b", re.I)),
    ("IKO certified", re.compile(r"\bIKO\s+[Cc]ertified\b", re.I)),
    ("TAMKO certified", re.compile(r"\bTAMKO\s+[Cc]ertified\b", re.I)),
    ("Atlas certified", re.compile(r"\bAtlas\s+[Cc]ertified\b", re.I)),
    ("Pabco certified", re.compile(r"\bPabco\s+[Cc]ertified\b", re.I)),
    ("Eagle certified", re.compile(r"\bEagle\s+[Cc]ertified\b", re.I)),
    ("DaVinci certified", re.compile(r"\bDaVinci\s+[Cc]ertified\b", re.I)),
    ("Brava certified", re.compile(r"\bBrava\s+[Cc]ertified\b", re.I)),
    ("F-Wave certified", re.compile(r"\bF[\s-]Wave\s+[Cc]ertified\b", re.I)),
    ("Decra certified", re.compile(r"\bDecra\s+[Cc]ertified\b", re.I)),
    ("Interlock certified", re.compile(r"\bInterlock\s+[Cc]ertified\b", re.I)),
    ("Mule-Hide certified", re.compile(r"\bMule[\s-]Hide\s+[Cc]ertified\b", re.I)),
    ("Polyglass certified", re.compile(r"\bPolyglass\s+[Cc]ertified\b", re.I)),
    ("Soprema certified", re.compile(r"\bSoprema\s+[Cc]ertified\b", re.I)),
    ("Versico certified", re.compile(r"\bVersico\s+[Cc]ertified\b", re.I)),
    ("Carlisle certified", re.compile(r"\bCarlisle\s+[Cc]ertified\b", re.I)),
    ("Firestone certified", re.compile(r"\bFirestone\s+[Cc]ertified\b", re.I)),
    ("GenFlex certified", re.compile(r"\bGenFlex\s+[Cc]ertified\b", re.I)),
    ("Johns Manville certified", re.compile(r"\bJohns\s+Manville\s+[Cc]ertified\b", re.I)),
    ("Siplast certified", re.compile(r"\bSiplast\s+[Cc]ertified\b", re.I)),
    ("Duro-Last certified", re.compile(r"\bDuro[\s-]Last\s+[Cc]ertified\b", re.I)),
    ("IB Roof certified", re.compile(r"\bIB\s+Roof\s+[Cc]ertified\b", re.I)),
    ("Elevate certified", re.compile(r"\bElevate\s+[Cc]ertified\b", re.I)),
    ("Huber certified", re.compile(r"\bHuber\s+[Cc]ertified\b", re.I)),
    ("LP certified", re.compile(r"\bLP\s+[Cc]ertified\b", re.I)),
    ("James Hardie certified", re.compile(r"\bJames\s+Hardie\s+[Cc]ertified\b", re.I)),
    ("Hardie certified", re.compile(r"\bHardie\s+[Cc]ertified\b", re.I)),
]


def extract_trust_signals(ctx):
    text = f"{ctx.footer_text} {ctx.headings_text} {ctx.visible_text}"
    found = set()
    for name, pat in _TRUST_SIGNAL_PATTERNS:
        if pat.search(text):
            found.add(name)
    return sorted(found)


# ======================================================================
# Awards extraction
# ======================================================================

_AWARD_PATTERNS = [
    ("Angi Super Service Award", re.compile(r"\bAngi\s+Super\s+Service\s+Award\b", re.I)),
    ("Angie's List Super Service", re.compile(r"\bAngie'?s?\s+List\s+Super\s+Service\b", re.I)),
    ("HomeAdvisor Top Rated", re.compile(r"\bHomeAdvisor\s+Top\s+Rated\b", re.I)),
    ("HomeAdvisor Elite", re.compile(r"\bHomeAdvisor\s+Elite\b", re.I)),
    ("Thumbtack Top Pro", re.compile(r"\bThumbtack\s+Top\s+Pro\b", re.I)),
    ("Houzz Best of", re.compile(r"\bHouzz\s+Best\s+of\b", re.I)),
    ("Guildmaster", re.compile(r"\bGuildmaster\b", re.I)),
    ("Remodeling Big50", re.compile(r"\bRemodeling\s+Big\s*50\b", re.I)),
    ("Remodeling 550", re.compile(r"\bRemodeling\s+550\b", re.I)),
    ("Inc 5000", re.compile(r"\bInc\.?\s*5000\b", re.I)),
    ("Inc 500", re.compile(r"\bInc\.?\s*500\b", re.I)),
    ("Fortune 500", re.compile(r"\bFortune\s+500\b", re.I)),
    ("Forbes", re.compile(r"\bForbes\b", re.I)),
    ("Entrepreneur Magazine", re.compile(r"\bEntrepreneur\s+Magazine\b", re.I)),
    ("Fast Company", re.compile(r"\bFast\s+Company\b", re.I)),
    ("Nextdoor Neighborhood Fave", re.compile(r"\bNextdoor\s+Neighborhood\s+Fave\b", re.I)),
    ("Nextdoor Favorite", re.compile(r"\bNextdoor\s+Favorite\b", re.I)),
    ("Qualified Remodeler", re.compile(r"\bQualified\s+Remodeler\b", re.I)),
    ("Professional Remodeler", re.compile(r"\bProfessional\s+Remodeler\b", re.I)),
    ("Remodeling Magazine", re.compile(r"\bRemodeling\s+Magazine\b", re.I)),
    ("Best of", re.compile(r"\bBest\s+of\s+[A-Z][a-z]+\b")),
    ("#1", re.compile(r"\b#\s*1\b")),
    ("voted best", re.compile(r"\bvoted\s+best\b", re.I)),
    ("top rated", re.compile(r"\btop[\s-]rated\b", re.I)),
    ("award of excellence", re.compile(r"\baward\s+of\s+excellence\b", re.I)),
    ("president's award", re.compile(r"\bpresident'?s\s+award\b", re.I)),
    ("circle of excellence", re.compile(r"\bcircle\s+of\s+excellence\b", re.I)),
    ("hall of fame", re.compile(r"\bhall\s+of\s+fame\b", re.I)),
    ("lifetime achievement", re.compile(r"\blifetime\s+achievement\b", re.I)),
    ("gold star", re.compile(r"\bgold\s+star\b", re.I)),
    ("platinum award", re.compile(r"\bplatinum\s+award\b", re.I)),
    ("diamond award", re.compile(r"\bdiamond\s+award\b", re.I)),
    ("gold award", re.compile(r"\bgold\s+award\b", re.I)),
    ("silver award", re.compile(r"\bsilver\s+award\b", re.I)),
    ("bronze award", re.compile(r"\bbronze\s+award\b", re.I)),
    ("readers choice", re.compile(r"\breaders?\s+choice\b", re.I)),
    ("people's choice", re.compile(r"\bpeople'?s\s+choice\b", re.I)),
    ("customer choice", re.compile(r"\bcustomer\s+choice\b", re.I)),
    ("dealer of the year", re.compile(r"\bdealer\s+of\s+the\s+year\b", re.I)),
    ("contractor of the year", re.compile(r"\bcontractor\s+of\s+the\s+year\b", re.I)),
    ("builder of the year", re.compile(r"\bbuilder\s+of\s+the\s+year\b", re.I)),
    ("remodeler of the year", re.compile(r"\bremodeler\s+of\s+the\s+year\b", re.I)),
    ("roofer of the year", re.compile(r"\broofer\s+of\s+the\s+year\b", re.I)),
    ("business of the year", re.compile(r"\bbusiness\s+of\s+the\s+year\b", re.I)),
    ("small business of the year", re.compile(r"\bsmall\s+business\s+of\s+the\s+year\b", re.I)),
]


def extract_awards(ctx):
    text = f"{ctx.footer_text} {ctx.headings_text} {ctx.visible_text}"
    found = set()
    for name, pat in _AWARD_PATTERNS:
        if pat.search(text):
            found.add(name)
    return sorted(found)


# ======================================================================
# Certifications extraction
# ======================================================================

_CERTIFICATION_PATTERNS = [
    ("GAF Master Elite", re.compile(r"\bGAF\s+Master\s+Elite\b", re.I)),
    ("GAF Certified Weather Stopper", re.compile(r"\bGAF\s+Certified\s+Weather\s+Stopper\b", re.I)),
    ("Owens Corning Preferred", re.compile(r"\bOwens\s+Corning\s+Preferred\b", re.I)),
    ("Owens Corning Platinum", re.compile(r"\bOwens\s+Corning\s+Platinum\b", re.I)),
    ("CertainTeed Select ShingleMaster", re.compile(r"\bCertainTeed\s+Select\s+ShingleMaster\b", re.I)),
    ("CertainTeed ShingleMaster", re.compile(r"\bCertainTeed\s+ShingleMaster\b", re.I)),
    ("CertainTeed Master Shingle Applicator", re.compile(r"\bCertainTeed\s+Master\s+Shingle\s+Applicator\b", re.I)),
    ("Malarkey Certified Residential", re.compile(r"\bMalarkey\s+Certified\s+Residential\b", re.I)),
    ("Malarkey Certified Commercial", re.compile(r"\bMalarkey\s+Certified\s+Commercial\b", re.I)),
    ("Malarkey Emerald Premium", re.compile(r"\bMalarkey\s+Emerald\s+Premium\b", re.I)),
    ("Malarkey Emerald Pro", re.compile(r"\bMalarkey\s+Emerald\s+Pro\b", re.I)),
    ("IKO ROOFPRO", re.compile(r"\bIKO\s+ROOFPRO\b", re.I)),
    ("IKO CROWN", re.compile(r"\bIKO\s+CROWN\b", re.I)),
    ("TAMKO Pro", re.compile(r"\bTAMKO\s+Pro\b", re.I)),
    ("TAMKO Master", re.compile(r"\bTAMKO\s+Master\b", re.I)),
    ("TAMKO Elite", re.compile(r"\bTAMKO\s+Elite\b", re.I)),
    ("Atlas Pro", re.compile(r"\bAtlas\s+Pro\b", re.I)),
    ("Atlas Select", re.compile(r"\bAtlas\s+Select\b", re.I)),
    ("Atlas Diamond", re.compile(r"\bAtlas\s+Diamond\b", re.I)),
    ("Atlas Platinum", re.compile(r"\bAtlas\s+Platinum\b", re.I)),
    ("Pabco Premier", re.compile(r"\bPabco\s+Premier\b", re.I)),
    ("Pabco Paramount", re.compile(r"\bPabco\s+Paramount\b", re.I)),
    ("Eagle Select", re.compile(r"\bEagle\s+Select\b", re.I)),
    ("Eagle Premium", re.compile(r"\bEagle\s+Premium\b", re.I)),
    ("DaVinci Masterpiece", re.compile(r"\bDaVinci\s+Masterpiece\b", re.I)),
    ("DaVinci Select", re.compile(r"\bDaVinci\s+Select\b", re.I)),
    ("Brava Preferred", re.compile(r"\bBrava\s+Preferred\b", re.I)),
    ("Brava Elite", re.compile(r"\bBrava\s+Elite\b", re.I)),
    ("F-Wave Preferred", re.compile(r"\bF[\s-]Wave\s+Preferred\b", re.I)),
    ("F-Wave Elite", re.compile(r"\bF[\s-]Wave\s+Elite\b", re.I)),
    ("Decra Preferred", re.compile(r"\bDecra\s+Preferred\b", re.I)),
    ("Decra Elite", re.compile(r"\bDecra\s+Elite\b", re.I)),
    ("Interlock Preferred", re.compile(r"\bInterlock\s+Preferred\b", re.I)),
    ("Interlock Elite", re.compile(r"\bInterlock\s+Elite\b", re.I)),
    ("Mule-Hide Preferred", re.compile(r"\bMule[\s-]Hide\s+Preferred\b", re.I)),
    ("Mule-Hide Elite", re.compile(r"\bMule[\s-]Hide\s+Elite\b", re.I)),
    ("Polyglass Preferred", re.compile(r"\bPolyglass\s+Preferred\b", re.I)),
    ("Polyglass Elite", re.compile(r"\bPolyglass\s+Elite\b", re.I)),
    ("Soprema Preferred", re.compile(r"\bSoprema\s+Preferred\b", re.I)),
    ("Soprema Elite", re.compile(r"\bSoprema\s+Elite\b", re.I)),
    ("Versico Preferred", re.compile(r"\bVersico\s+Preferred\b", re.I)),
    ("Versico Elite", re.compile(r"\bVersico\s+Elite\b", re.I)),
    ("Carlisle Preferred", re.compile(r"\bCarlisle\s+Preferred\b", re.I)),
    ("Carlisle Elite", re.compile(r"\bCarlisle\s+Elite\b", re.I)),
    ("Firestone Preferred", re.compile(r"\bFirestone\s+Preferred\b", re.I)),
    ("Firestone Elite", re.compile(r"\bFirestone\s+Elite\b", re.I)),
    ("GenFlex Preferred", re.compile(r"\bGenFlex\s+Preferred\b", re.I)),
    ("GenFlex Elite", re.compile(r"\bGenFlex\s+Elite\b", re.I)),
    ("Johns Manville Preferred", re.compile(r"\bJohns\s+Manville\s+Preferred\b", re.I)),
    ("Johns Manville Elite", re.compile(r"\bJohns\s+Manville\s+Elite\b", re.I)),
    ("Siplast Preferred", re.compile(r"\bSiplast\s+Preferred\b", re.I)),
    ("Siplast Elite", re.compile(r"\bSiplast\s+Elite\b", re.I)),
    ("Duro-Last Preferred", re.compile(r"\bDuro[\s-]Last\s+Preferred\b", re.I)),
    ("Duro-Last Elite", re.compile(r"\bDuro[\s-]Last\s+Elite\b", re.I)),
    ("IB Roof Preferred", re.compile(r"\bIB\s+Roof\s+Preferred\b", re.I)),
    ("IB Roof Elite", re.compile(r"\bIB\s+Roof\s+Elite\b", re.I)),
    ("Elevate Preferred", re.compile(r"\bElevate\s+Preferred\b", re.I)),
    ("Elevate Elite", re.compile(r"\bElevate\s+Elite\b", re.I)),
    ("Huber Preferred", re.compile(r"\bHuber\s+Preferred\b", re.I)),
    ("Huber Elite", re.compile(r"\bHuber\s+Elite\b", re.I)),
    ("LP Preferred", re.compile(r"\bLP\s+Preferred\b", re.I)),
    ("LP Elite", re.compile(r"\bLP\s+Elite\b", re.I)),
    ("James Hardie Preferred", re.compile(r"\bJames\s+Hardie\s+Preferred\b", re.I)),
    ("James Hardie Elite", re.compile(r"\bJames\s+Hardie\s+Elite\b", re.I)),
    ("Hardie Preferred", re.compile(r"\bHardie\s+Preferred\b", re.I)),
    ("Hardie Elite", re.compile(r"\bHardie\s+Elite\b", re.I)),
    ("LEED Certified", re.compile(r"\bLEED\s+[Cc]ertified\b", re.I)),
    ("Energy Star Certified", re.compile(r"\bEnergy\s+Star\s+[Cc]ertified\b", re.I)),
    ("B Corp Certified", re.compile(r"\bB\s+Corp\s+[Cc]ertified\b", re.I)),
    ("EPA Lead-Safe Certified", re.compile(r"\bEPA\s+[Ll]ead[\s-][Ss]afe\s+[Cc]ertified\b", re.I)),
    ("OSHA Certified", re.compile(r"\bOSHA\s+[Cc]ertified\b", re.I)),
    ("NAHB Certified", re.compile(r"\bNAHB\s+[Cc]ertified\b", re.I)),
    ("NARI Certified", re.compile(r"\bNARI\s+[Cc]ertified\b", re.I)),
    ("NKBA Certified", re.compile(r"\bNKBA\s+[Cc]ertified\b", re.I)),
    ("GAF Certified", re.compile(r"\bGAF\s+[Cc]ertified\b", re.I)),
    ("Owens Corning Certified", re.compile(r"\bOwens\s+Corning\s+[Cc]ertified\b", re.I)),
    ("CertainTeed Certified", re.compile(r"\bCertainTeed\s+[Cc]ertified\b", re.I)),
    ("Malarkey Certified", re.compile(r"\bMalarkey\s+[Cc]ertified\b", re.I)),
    ("IKO Certified", re.compile(r"\bIKO\s+[Cc]ertified\b", re.I)),
    ("TAMKO Certified", re.compile(r"\bTAMKO\s+[Cc]ertified\b", re.I)),
    ("Atlas Certified", re.compile(r"\bAtlas\s+[Cc]ertified\b", re.I)),
    ("Pabco Certified", re.compile(r"\bPabco\s+[Cc]ertified\b", re.I)),
    ("Eagle Certified", re.compile(r"\bEagle\s+[Cc]ertified\b", re.I)),
    ("DaVinci Certified", re.compile(r"\bDaVinci\s+[Cc]ertified\b", re.I)),
    ("Brava Certified", re.compile(r"\bBrava\s+[Cc]ertified\b", re.I)),
    ("F-Wave Certified", re.compile(r"\bF[\s-]Wave\s+[Cc]ertified\b", re.I)),
    ("Decra Certified", re.compile(r"\bDecra\s+[Cc]ertified\b", re.I)),
    ("Interlock Certified", re.compile(r"\bInterlock\s+[Cc]ertified\b", re.I)),
    ("Mule-Hide Certified", re.compile(r"\bMule[\s-]Hide\s+[Cc]ertified\b", re.I)),
    ("Polyglass Certified", re.compile(r"\bPolyglass\s+[Cc]ertified\b", re.I)),
    ("Soprema Certified", re.compile(r"\bSoprema\s+[Cc]ertified\b", re.I)),
    ("Versico Certified", re.compile(r"\bVersico\s+[Cc]ertified\b", re.I)),
    ("Carlisle Certified", re.compile(r"\bCarlisle\s+[Cc]ertified\b", re.I)),
    ("Firestone Certified", re.compile(r"\bFirestone\s+[Cc]ertified\b", re.I)),
    ("GenFlex Certified", re.compile(r"\bGenFlex\s+[Cc]ertified\b", re.I)),
    ("Johns Manville Certified", re.compile(r"\bJohns\s+Manville\s+[Cc]ertified\b", re.I)),
    ("Siplast Certified", re.compile(r"\bSiplast\s+[Cc]ertified\b", re.I)),
    ("Duro-Last Certified", re.compile(r"\bDuro[\s-]Last\s+[Cc]ertified\b", re.I)),
    ("IB Roof Certified", re.compile(r"\bIB\s+Roof\s+[Cc]ertified\b", re.I)),
    ("Elevate Certified", re.compile(r"\bElevate\s+[Cc]ertified\b", re.I)),
    ("Huber Certified", re.compile(r"\bHuber\s+[Cc]ertified\b", re.I)),
    ("LP Certified", re.compile(r"\bLP\s+[Cc]ertified\b", re.I)),
    ("James Hardie Certified", re.compile(r"\bJames\s+Hardie\s+[Cc]ertified\b", re.I)),
    ("Hardie Certified", re.compile(r"\bHardie\s+[Cc]ertified\b", re.I)),
    ("Tamko Certified", re.compile(r"\bTamko\s+[Cc]ertified\b", re.I)),
]


def extract_certifications(ctx):
    text = f"{ctx.footer_text} {ctx.headings_text} {ctx.visible_text}"
    found = set()
    for name, pat in _CERTIFICATION_PATTERNS:
        if pat.search(text):
            found.add(name)
    return sorted(found)


# ======================================================================
# Guarantees extraction
# ======================================================================

_GUARANTEE_PATTERNS = [
    ("lifetime workmanship warranty", re.compile(r"\blifetime\s+workmanship\s+warranty\b", re.I)),
    ("satisfaction guarantee", re.compile(r"\bsatisfaction\s+guarantee\b", re.I)),
    ("10-year labor warranty", re.compile(r"\b10[\s-]year\s+labor\s+warranty\b", re.I)),
    ("free inspection guarantee", re.compile(r"\bfree\s+inspection\s+guarantee\b", re.I)),
    ("money-back guarantee", re.compile(r"\bmoney[\s-]back\s+guarantee\b", re.I)),
    ("100% satisfaction guarantee", re.compile(r"\b100%?\s+satisfaction\s+guarantee\b", re.I)),
    ("lifetime guarantee", re.compile(r"\blifetime\s+guarantee\b", re.I)),
    ("lifetime warranty", re.compile(r"\blifetime\s+warranty\b", re.I)),
    ("limited lifetime warranty", re.compile(r"\blimited\s+lifetime\s+warranty\b", re.I)),
    ("extended warranty", re.compile(r"\bextended\s+warranty\b", re.I)),
    ("transferable warranty", re.compile(r"\btransferable\s+warranty\b", re.I)),
    ("parts and labor warranty", re.compile(r"\bparts?\s+(?:and|&)\s+labor\s+warranty\b", re.I)),
    ("written warranty", re.compile(r"\bwritten\s+warranty\b", re.I)),
    ("no-surprise guarantee", re.compile(r"\bno[\s-]surprise\s+guarantee\b", re.I)),
    ("done right guarantee", re.compile(r"\bdone\s+right\s+guarantee\b", re.I)),
    ("clean guarantee", re.compile(r"\bclean\s+guarantee\b", re.I)),
    ("on-time guarantee", re.compile(r"\bon[\s-]time\s+guarantee\b", re.I)),
    ("lowest price guarantee", re.compile(r"\blowest\s+price\s+guarantee\b", re.I)),
    ("best price guarantee", re.compile(r"\bbest\s+price\s+guarantee\b", re.I)),
    ("price match guarantee", re.compile(r"\bprice\s+match\s+guarantee\b", re.I)),
    ("price beat guarantee", re.compile(r"\bprice\s+beat\s+guarantee\b", re.I)),
    ("quality guarantee", re.compile(r"\bquality\s+guarantee\b", re.I)),
    ("quality guaranteed", re.compile(r"\bquality\s+guaranteed\b", re.I)),
    ("results guaranteed", re.compile(r"\bresults\s+guaranteed\b", re.I)),
    ("manufacturer-backed warranty", re.compile(r"\bmanufacturer[\s-]backed\s+warranty\b", re.I)),
    ("manufacturer warranty", re.compile(r"\bmanufacturer\s+warranty\b", re.I)),
    ("workmanship warranty", re.compile(r"\bworkmanship\s+warranty\b", re.I)),
    ("labor warranty", re.compile(r"\blabor\s+warranty\b", re.I)),
    ("5-year warranty", re.compile(r"\b5[\s-]year\s+warranty\b", re.I)),
    ("10-year warranty", re.compile(r"\b10[\s-]year\s+warranty\b", re.I)),
    ("15-year warranty", re.compile(r"\b15[\s-]year\s+warranty\b", re.I)),
    ("20-year warranty", re.compile(r"\b20[\s-]year\s+warranty\b", re.I)),
    ("25-year warranty", re.compile(r"\b25[\s-]year\s+warranty\b", re.I)),
    ("30-year warranty", re.compile(r"\b30[\s-]year\s+warranty\b", re.I)),
    ("50-year warranty", re.compile(r"\b50[\s-]year\s+warranty\b", re.I)),
    ("we guarantee", re.compile(r"\bwe\s+guarantee\b", re.I)),
    ("we promise", re.compile(r"\bwe\s+promise\b", re.I)),
]


def extract_guarantees(ctx):
    text = f"{ctx.footer_text} {ctx.headings_text} {ctx.visible_text}"
    found = set()
    for name, pat in _GUARANTEE_PATTERNS:
        if pat.search(text):
            found.add(name)
    return sorted(found)


# ======================================================================
# Years in business extraction
# ======================================================================

_SINCE_YEAR_RE = re.compile(r"(?:since|established|founded|est\.?)\s*(?:in\s+)?(\d{4})", re.IGNORECASE)
_YEARS_EXPERIENCE_RE = re.compile(
    r"(?:over\s+)?(\d+)\s*(?:\+\s*)?years?\s*(?:of\s*)?(?:experience|in\s+business|serving)",
    re.IGNORECASE,
)
_SERVING_SINCE_RE = re.compile(
    r"serving\s+(?:\w+\s+){0,3}(?:for\s+)?(?:over\s+)?(\d+)\s*(?:\+\s*)?years?",
    re.IGNORECASE,
)


def extract_years_in_business(ctx):
    text = f"{ctx.footer_text} {ctx.headings_text} {ctx.visible_text}"
    current_year = datetime.now().year

    # 1. JSON-LD foundingYear
    for ld in ctx.jsonld:
        fy = _get_jsonld_value(ld, "foundingYear")
        if fy:
            try:
                year = int(str(fy))
                if 1800 <= year <= current_year:
                    return str(current_year - year)
            except (ValueError, TypeError):
                pass

    # 2. "Since YYYY" or "Est. YYYY"
    m = _SINCE_YEAR_RE.search(text)
    if m:
        try:
            year = int(m.group(1))
            if 1800 <= year <= current_year:
                return str(current_year - year)
        except ValueError:
            pass

    # 3. "X years of experience" or "X years in business"
    m = _YEARS_EXPERIENCE_RE.search(text)
    if m:
        try:
            years = int(m.group(1))
            if 1 <= years <= 200:
                return str(years)
        except ValueError:
            pass

    # 4. "Serving ... for X years"
    m = _SERVING_SINCE_RE.search(text)
    if m:
        try:
            years = int(m.group(1))
            if 1 <= years <= 200:
                return str(years)
        except ValueError:
            pass

    return ""


# ======================================================================
# Orchestrator
# ======================================================================

def extract_business_intel(ctx):
    return {
        "phone": extract_phone(ctx),
        "location": extract_location(ctx),
        "service_area": extract_service_area(ctx),
        "services": extract_services(ctx),
        "categories": extract_categories(ctx),
        "differentiators": extract_differentiators(ctx),
        "trust_signals": extract_trust_signals(ctx),
        "awards": extract_awards(ctx),
        "certifications": extract_certifications(ctx),
        "guarantees": extract_guarantees(ctx),
        "years_in_business": extract_years_in_business(ctx),
    }