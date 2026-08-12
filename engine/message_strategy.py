"""Message Strategy Engine for BillboardAI — Sprint 2D.

Determines WHAT a billboard should communicate given a BrandProfile.
Produces structured MessageStrategy candidates with evidence-traceable claims.

Architecture:
    WebsiteScraper → BrandProfile → MessageStrategyEngine → MessageStrategy[]

This is the STRATEGY layer only:
    MessageStrategy  = WHAT TO SAY (this sprint)
    Future Copy Engine = HOW TO SAY IT
    Future Concept Engine = HOW TO PRESENT IT

Design principles:
    - Evidence-first: every claim must be traceable to BrandProfile fields.
    - Deterministic: no LLM, no ML, no external APIs.
    - Generic: no industry-specific hardcoding beyond a minimal problem-frame map.
    - Concise: primary_message targets 2-7 words, supporting_proof 2-5 words.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields as dc_fields, replace
from typing import Any, Dict, List, Optional, Set, Tuple

from engine.brand_profile import BrandProfile


# ======================================================================
# Strategy type constants
# ======================================================================

TRUST_LED = "TRUST_LED"
SERVICE_LED = "SERVICE_LED"
OFFER_LED = "OFFER_LED"
LOCAL_AUTHORITY = "LOCAL_AUTHORITY"
PROBLEM_LED = "PROBLEM_LED"

STRATEGY_TYPES: Tuple[str, ...] = (
    TRUST_LED,
    SERVICE_LED,
    OFFER_LED,
    LOCAL_AUTHORITY,
    PROBLEM_LED,
)


# ======================================================================
# MessageStrategy dataclass
# ======================================================================

@dataclass
class MessageStrategy:
    """A structured message strategy candidate for billboard communication.

    Represents WHAT to communicate, not HOW to phrase it.
    The future Copy Engine will handle polished wording variants.
    """

    strategy_type: str = ""
    primary_message: str = ""
    supporting_proof: List[str] = field(default_factory=list)
    cta: str = ""
    rationale: str = ""
    score: float = 0.0
    evidence: List[str] = field(default_factory=list)

    # Optional fields
    service_focus: str = ""
    geographic_focus: str = ""
    phone: str = ""
    confidence: float = 0.0

    # ------------------------------------------------------------------
    # Serialization (forward-compatible, same pattern as BrandProfile)
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary for JSON output."""
        return {
            "strategy_type": self.strategy_type,
            "primary_message": self.primary_message,
            "supporting_proof": list(self.supporting_proof),
            "cta": self.cta,
            "rationale": self.rationale,
            "score": self.score,
            "evidence": list(self.evidence),
            "service_focus": self.service_focus,
            "geographic_focus": self.geographic_focus,
            "phone": self.phone,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageStrategy":
        """Deserialize from a dictionary.

        Unknown fields are silently ignored (forward-compatible).
        Missing optional fields receive safe defaults.
        """
        if not data:
            return cls()

        known = {f.name for f in dc_fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}

        for list_key in ("supporting_proof", "evidence"):
            val = filtered.get(list_key)
            if not isinstance(val, list):
                filtered[list_key] = []

        for float_key in ("score", "confidence"):
            try:
                filtered[float_key] = float(filtered.get(float_key, 0.0))
            except (TypeError, ValueError):
                filtered[float_key] = 0.0

        for str_key in (
            "strategy_type", "primary_message", "cta", "rationale",
            "service_focus", "geographic_focus", "phone",
        ):
            val = filtered.get(str_key)
            if not isinstance(val, str):
                filtered[str_key] = str(val) if val else ""

        return cls(**filtered)


def _normalize_creative_locality(value: str) -> str:
    """Return a safe locality string for customer-facing creative use.

    Only trims/normalizes whitespace; it never invents or parses geography.
    """
    if not isinstance(value, str):
        return ""
    cleaned = " ".join(value.split())
    return cleaned.strip()


def _localized_service_message(service_focus: str, locality: str) -> str:
    """Return a concise localized service-led candidate when feasible."""
    service = (service_focus or "").strip()
    city = _normalize_creative_locality(locality)
    if not service or not city:
        return ""
    candidate = f"{service.title()} In {city}"
    if len(candidate.split()) > 7 or len(candidate) > 40:
        fallback = f"Serving {city}"
        return fallback if len(fallback.split()) <= 4 and len(fallback) <= 30 else ""
    return candidate


def _localized_category_message(profile: BrandProfile, locality: str) -> str:
    """Return a concise locality-aware category headline when supported."""
    city = _normalize_creative_locality(locality)
    if not city:
        return ""

    categories = [c.strip() for c in profile.categories if isinstance(c, str) and c.strip()]
    services = [s.strip() for s in profile.services if isinstance(s, str) and s.strip()]
    corpus = " ".join(categories + services).lower()

    if "dent" in corpus:
        candidate = f"Trusted Dental Care In {city}"
    elif "real estate" in corpus or "realtor" in corpus:
        candidate = f"Your {city} Realtor"
    elif any(token in corpus for token in ("roof", "contractor", "plumb", "hvac", "paint", "remodel", "repair")):
        candidate = f"Trusted Local Service In {city}"
    else:
        candidate = ""

    if candidate and (len(candidate.split()) > 7 or len(candidate) > 40):
        return ""
    return candidate


def _compact_locality_message(locality: str, *, prefix: str = "Serving") -> str:
    city = _normalize_creative_locality(locality)
    if not city:
        return ""
    candidate = f"{prefix} {city}".strip()
    if len(candidate.split()) > 4 or len(candidate) > 30:
        return ""
    return candidate


def _inject_localized_variants(
    profile: BrandProfile,
    candidates: List[MessageStrategy],
    creative_locality: str,
) -> List[MessageStrategy]:
    """Extend the existing strategy set with optional locality-aware variants.

    Variants compete with existing strategies; locality never forces itself.
    """
    city = _normalize_creative_locality(creative_locality)
    if not city:
        return candidates

    variants: List[MessageStrategy] = []
    for strategy in candidates:
        if strategy is None:
            continue

        localized_primary = ""
        localized_geo = city

        if strategy.strategy_type == LOCAL_AUTHORITY:
            localized_primary = _compact_locality_message(city)
        elif strategy.strategy_type == SERVICE_LED:
            localized_primary = _localized_service_message(strategy.service_focus or strategy.primary_message, city)
        elif strategy.strategy_type == TRUST_LED:
            localized_primary = _localized_category_message(profile, city)

        if not localized_primary:
            continue
        if localized_primary.strip().lower() == (strategy.primary_message or "").strip().lower():
            continue

        evidence = list(strategy.evidence)
        if "creative_locality" not in evidence:
            evidence.append("creative_locality")
        proof = list(strategy.supporting_proof)
        if city not in proof and len(proof) < 2:
            proof.append(city)
        proof = [p for p in proof if p.strip().lower() != localized_primary.strip().lower()][:2]
        localized = replace(
            strategy,
            primary_message=localized_primary,
            supporting_proof=proof,
            geographic_focus=localized_geo,
            evidence=evidence,
            rationale=f"{strategy.rationale} Creative locality: {city}.",
            score=min(1.0, round(strategy.score + 0.04, 2)),
            confidence=min(1.0, round(strategy.confidence + 0.02, 2)),
        )
        variants.append(localized)

    return candidates + variants


# ======================================================================
# Minimal problem-frame mapping (bounded proof-of-concept)
# ======================================================================
# These are the ONLY service→problem transformations allowed.
# The future Copy Engine will generate richer wording variants.
# Do NOT expand this into a large phrase library in this sprint.

_PROBLEM_FRAME_MAP: Dict[str, str] = {
    "roof replacement": "Need a New Roof?",
    "roof repair": "Roof Problems?",
    "roof leak repair": "Roof Leaking?",
    "emergency roof repair": "Roof Emergency?",
    "emergency service": "Emergency?",
    "water damage restoration": "Water Damage?",
    "fire damage restoration": "Fire Damage?",
    "mold remediation": "Mold Problem?",
    "foundation repair": "Foundation Issues?",
    "basement waterproofing": "Wet Basement?",
    "furnace repair": "Furnace Not Working?",
    "ac repair": "AC Not Cooling?",
    "plumbing repair": "Plumbing Issue?",
    "drain cleaning": "Clogged Drain?",
    "water heater": "No Hot Water?",
    "appliance repair": "Appliance Broken?",
    "garage door": "Garage Door Stuck?",
    "auto repair": "Car Trouble?",
    "brake repair": "Brake Problems?",
    "computer repair": "Computer Issues?",
    "pest control": "Pest Problem?",
    "tree service": "Tree Trouble?",
    "locksmith": "Locked Out?",
    "towing": "Need a Tow?",
}


def _problem_frame_for_service(service: str) -> Optional[str]:
    """Return a problem-frame message for a verified service, or None.

    Only exact matches in _PROBLEM_FRAME_MAP are allowed.
    No fuzzy matching, no inference, no fabrication.
    """
    return _PROBLEM_FRAME_MAP.get(service.lower())


# ======================================================================
# Primary service selection
# ======================================================================

# Services that are typically ancillary (not the core business).
_ANCILLARY_SERVICES: Set[str] = {
    "siding", "gutters", "windows", "doors", "insulation",
    "gutter installation", "gutter repair", "gutter cleaning",
    "seamless gutters", "window installation", "window replacement",
    "door installation", "door replacement", "attic insulation",
    "spray foam insulation", "deck building", "deck repair",
    "fence installation", "chimney repair", "exterior painting",
    "gutter guard installation", "leaf guard",
}

# Services that represent core trade work (preferred over ancillary).
_CORE_SERVICE_PRIORITY: Dict[str, int] = {
    # Roofing core
    "residential roofing": 10,
    "commercial roofing": 10,
    "roof replacement": 9,
    "roof repair": 9,
    "roof installation": 9,
    "roofing": 8,
    "roofing contractor": 8,
    "roof inspection": 7,
    "roof maintenance": 7,
    "roof restoration": 7,
    "metal roofing": 7,
    "flat roofing": 7,
    "emergency roof repair": 6,
    "storm damage repair": 6,
    # Dental core
    "general dentistry": 10,
    "cosmetic dentistry": 8,
    "dental implants": 7,
    "teeth whitening": 5,
    # Real estate core
    "real estate": 10,
    # Medical core
    "primary care": 10,
    "family medicine": 10,
    "urgent care": 8,
    "physical therapy": 7,
    # Plumbing core
    "plumbing repair": 10,
    "water heater": 8,
    "drain cleaning": 7,
    # HVAC core
    "hvac repair": 10,
    "air conditioning": 9,
    "furnace repair": 8,
    "ac repair": 8,
    # Auto core
    "auto repair": 10,
    "brake repair": 8,
    "oil change": 7,
    "collision repair": 7,
    # Other core
    "landscaping services": 10,
    "tree trimming": 8,
    "lawn mowing": 7,
    "snow removal": 7,
    "electrical repair": 10,
    "carpet cleaning": 10,
    "pressure washing": 10,
    "pest control": 10,
    "home inspection": 10,
    "general contractor": 10,
    "new construction": 10,
    "commercial construction": 10,
    "kitchen remodeling": 9,
    "bathroom remodeling": 9,
    "whole home remodeling": 9,
    "concrete work": 10,
    "drywall repair": 8,
    "painting services": 10,
    "flooring installation": 9,
    "welding services": 10,
    "excavation": 10,
    "towing": 10,
    "locksmith": 10,
    "appliance repair": 10,
    "garage door": 10,
    "foundation repair": 10,
    "basement waterproofing": 9,
    "water damage restoration": 10,
    "fire damage restoration": 10,
    "mold remediation": 9,
    "computer repair": 10,
    "web design": 10,
    "software development": 10,
    "bookkeeping": 10,
    "tax preparation": 10,
    "financial planning": 10,
    "event planning": 10,
    "personal training": 10,
    "pet grooming": 10,
    "dog walking": 8,
    "photography": 10,
    "videography": 10,
    "catering": 10,
    "florist": 10,
    "tutoring": 10,
    "accounting": 10,
    "insurance": 10,
    "storage": 10,
    "moving": 10,
    "junk removal": 10,
    "dumpster rental": 8,
    "home improvement": 8,
    "interior design": 10,
    "fencing services": 8,
    "deck construction": 8,
    "patio installation": 7,
    "driveway paving": 8,
    "sealcoating": 7,
    "office cleaning": 10,
    "deep cleaning": 9,
    "move out cleaning": 8,
    "air duct cleaning": 8,
    "dryer vent cleaning": 7,
    "window cleaning": 9,
    "power washing": 9,
    "soft washing": 8,
    "roof coating": 7,
    "roof sealing": 7,
    "roof leak repair": 8,
    "flat roof repair": 8,
    "tree service": 10,
    "lawn care": 10,
    "snow removal": 7,
    "auto body": 9,
    "car wash": 8,
    "oil change": 7,
    "collision repair": 8,
    "tire": 7,
    "transmission": 7,
    "muffler": 6,
    "dentistry": 10,
    "orthodontics": 8,
    "chiropractic": 10,
    "massage": 8,
    "physical therapy": 8,
    "counseling": 10,
    "mental health": 10,
    "home health": 10,
    "assisted living": 10,
    "childcare": 10,
    "veterinary": 10,
    "pet care": 10,
    "salon": 10,
    "barber": 10,
    "spa": 10,
    "fitness": 10,
    "gym": 10,
    "yoga": 8,
    "martial arts": 8,
    "dance": 8,
    "music lessons": 8,
    "art classes": 7,
    "cooking classes": 7,
    "language tutoring": 8,
    "driving school": 8,
    "real estate": 10,
    "property management": 10,
    "home staging": 7,
    "appraisal": 8,
    "inspection": 8,
    "mortgage": 9,
    "lending": 9,
    "banking": 10,
    "investment": 9,
    "tax": 9,
    "payroll": 8,
    "audit": 8,
    "legal": 10,
    "attorney": 10,
    "lawyer": 10,
    "mediation": 8,
    "notary": 7,
    "translation": 8,
    "virtual assistant": 8,
    "call center": 8,
    "data entry": 7,
    "hosting": 8,
    "seo": 8,
    "social media": 8,
    "content": 7,
    "video": 8,
    "audio": 7,
    "animation": 7,
    "game": 7,
    "drone": 7,
    "security": 9,
    "alarm": 8,
    "surveillance": 8,
    "private investigation": 8,
    "background check": 7,
    "printing": 8,
    "shipping": 8,
    "courier": 8,
    "freight": 8,
    "warehouse": 8,
    "packaging": 7,
    "manufacturing": 9,
    "wholesale": 8,
    "retail": 8,
    "restaurant": 9,
    "cafe": 8,
    "bakery": 8,
    "brewery": 8,
    "winery": 8,
    "distillery": 8,
    "coffee": 8,
    "food truck": 8,
    "meal prep": 7,
    "grocery": 8,
    "liquor": 7,
    "convenience": 7,
    "jewelry": 8,
    "clothing": 8,
    "shoes": 7,
    "sporting goods": 7,
    "bicycle": 7,
    "motorcycle": 7,
    "boat dealer": 7,
    "rv": 7,
    "furniture": 8,
    "appliance": 7,
    "electronics": 7,
    "hardware": 8,
    "paint store": 7,
    "nursery": 7,
    "pet store": 7,
    "bookstore": 7,
    "music store": 7,
    "hobby": 7,
    "antique": 7,
    "thrift": 7,
    "pawn": 7,
    "auction": 7,
    "rental": 7,
    "leasing": 7,
    "financing": 7,
    "business services": 8,
    "consulting": 8,
    "coaching": 8,
    "training": 8,
    "publishing": 8,
    "music": 8,
    "art": 8,
    "theater": 8,
    "museum": 8,
    "library": 7,
    "park": 7,
    "zoo": 7,
    "golf": 7,
    "sports": 7,
    "camp": 7,
    "marina": 7,
    "fishing": 7,
    "hunting": 7,
    "ski": 7,
    "scuba": 7,
    "skydiving": 7,
    "rafting": 7,
    "zip line": 7,
    "escape room": 7,
    "axe throwing": 7,
    "hotel": 8,
    "motel": 7,
    "inn": 7,
    "lodging": 7,
    "resort": 7,
    "airport service": 7,
    "car rental": 7,
    "limousine": 7,
    "taxi": 7,
    "bus": 7,
    "funeral": 8,
    "pharmacy": 8,
    "optometry": 8,
    "dermatology": 8,
    "cosmetic": 7,
    "weight loss": 7,
    "hearing": 7,
    "podiatry": 7,
    "acupuncture": 7,
    "energy": 7,
    "electric vehicle": 7,
    "generator": 7,
    "satellite": 7,
    "cable": 7,
    "telecom": 7,
    "office": 7,
    "franchise": 7,
    "nonprofit": 7,
    "education": 7,
    "religious": 7,
    "school": 7,
    "college": 7,
    "university": 7,
    "academy": 7,
    "church": 7,
    "ministry": 7,
    "temple": 7,
    "mosque": 7,
    "synagogue": 7,
}


def _select_primary_service(profile: BrandProfile) -> str:
    """Select the most likely primary service from a BrandProfile.

    Heuristics (in priority order):
    1. Multi-word specific services outrank single-word generic ones.
    2. Services aligned with the primary category get a boost.
    3. Core services outrank ancillary services.
    4. Higher explicit priority scores win.
    5. First occurrence breaks ties.

    Returns empty string if no services exist.
    """
    services = profile.services
    if not services:
        return ""

    categories = set(c.lower() for c in profile.categories)

    best_service = ""
    best_score = -1

    for svc in services:
        svc_lower = svc.lower()
        score = 0

        # Base priority from explicit mapping
        score += _CORE_SERVICE_PRIORITY.get(svc_lower, 5)

        # Multi-word services are more specific → bonus
        word_count = len(svc_lower.split())
        if word_count >= 3:
            score += 3
        elif word_count == 2:
            score += 2
        # Single-word services are generic → no bonus (but not penalized)

        # Category alignment bonus
        for cat in categories:
            if cat in svc_lower or svc_lower in cat:
                score += 3
                break

        # Ancillary penalty
        if svc_lower in _ANCILLARY_SERVICES:
            score -= 4

        if score > best_score:
            best_score = score
            best_service = svc

    return best_service


# ======================================================================
# CTA selection
# ======================================================================

def _select_cta(profile: BrandProfile) -> Tuple[str, str]:
    """Select an evidence-based CTA and return (cta_text, phone_used).

    Priority:
    1. If phone exists → "Call (XXX) XXX-XXXX"
    2. If free estimates → "Get a Free Estimate"
    3. Otherwise → "Learn More"

    Never invents URLs, phone numbers, or urgency language.
    """
    phone = profile.phone.strip()
    if phone:
        return f"Call {phone}", phone

    differentiators = [d.lower() for d in profile.differentiators]
    if "free estimates" in differentiators:
        return "Get a Free Estimate", ""

    return "Learn More", ""


# ======================================================================
# Supporting proof selection
# ======================================================================

def _select_supporting_proof(profile: BrandProfile, strategy_type: str) -> List[str]:
    """Select 1-2 concise, billboard-appropriate supporting facts.

    Prefers concrete facts over vague claims.
    Returns empty list if no suitable proof exists.
    """
    candidates: List[Tuple[str, int]] = []  # (text, priority)

    # Years in business — strong trust signal
    yib = profile.years_in_business.strip()
    if yib:
        try:
            years = int(yib)
            candidates.append((f"{years} Years in Business", 10))
        except ValueError:
            pass

    # Awards — high credibility
    for award in profile.awards:
        if "award-winning" in award.lower():
            candidates.append(("Award-Winning", 9))
        elif "best of" in award.lower():
            candidates.append(("Best of Award", 8))
        elif "top rated" in award.lower():
            candidates.append(("Top Rated", 7))
        elif "voted best" in award.lower():
            candidates.append(("Voted Best", 8))
        elif "#1" in award:
            candidates.append(("#1 Rated", 8))
        else:
            # Named award — use as-is if short enough
            if len(award) <= 30:
                candidates.append((award, 7))

    # Guarantees — strong for trust/offer
    for g in profile.guarantees:
        g_lower = g.lower()
        if "workmanship warranty" in g_lower:
            candidates.append(("Workmanship Warranty", 8))
        elif "manufacturer warranty" in g_lower:
            candidates.append(("Manufacturer Warranty", 7))
        elif "lifetime" in g_lower and "warranty" in g_lower:
            candidates.append(("Lifetime Warranty", 8))
        elif "satisfaction guarantee" in g_lower:
            candidates.append(("Satisfaction Guarantee", 7))
        elif "money-back" in g_lower:
            candidates.append(("Money-Back Guarantee", 7))
        elif "warranty" in g_lower:
            candidates.append(("Warranty Included", 6))
        elif "guarantee" in g_lower:
            candidates.append(("Guaranteed", 5))

    # Differentiators
    for d in profile.differentiators:
        d_lower = d.lower()
        if "free estimates" in d_lower:
            candidates.append(("Free Estimates", 8))
        elif "financing available" in d_lower:
            candidates.append(("Financing Available", 7))
        elif "family owned" in d_lower:
            candidates.append(("Family Owned", 6))
        elif "locally owned" in d_lower:
            candidates.append(("Locally Owned", 6))
        elif "licensed" in d_lower:
            candidates.append(("Licensed", 5))
        elif "insured" in d_lower:
            candidates.append(("Insured", 5))
        elif "bonded" in d_lower:
            candidates.append(("Bonded", 5))
        elif "same-day service" in d_lower:
            candidates.append(("Same-Day Service", 6))
        elif "emergency service" in d_lower:
            candidates.append(("Emergency Service", 6))
        elif "24/7" in d_lower:
            candidates.append(("24/7 Service", 6))
        elif "free inspection" in d_lower:
            candidates.append(("Free Inspections", 7))
        elif "free consultation" in d_lower:
            candidates.append(("Free Consultation", 7))
        elif "veteran owned" in d_lower:
            candidates.append(("Veteran Owned", 5))
        elif "woman owned" in d_lower:
            candidates.append(("Woman Owned", 5))
        elif "eco-friendly" in d_lower:
            candidates.append(("Eco-Friendly", 4))
        elif "no subcontractors" in d_lower:
            candidates.append(("No Subcontractors", 5))
        elif "upfront pricing" in d_lower:
            candidates.append(("Upfront Pricing", 5))
        elif "transparent pricing" in d_lower:
            candidates.append(("Transparent Pricing", 5))
        elif "mobile service" in d_lower:
            candidates.append(("Mobile Service", 5))
        elif "online booking" in d_lower:
            candidates.append(("Online Booking", 4))
        elif "custom solutions" in d_lower:
            candidates.append(("Custom Solutions", 4))
        elif "full-service" in d_lower:
            candidates.append(("Full-Service", 4))
        elif "hassle-free" in d_lower:
            candidates.append(("Hassle-Free", 4))
        elif "satisfaction guarantee" in d_lower:
            candidates.append(("Satisfaction Guarantee", 7))
        elif "money-back guarantee" in d_lower:
            candidates.append(("Money-Back Guarantee", 7))
        elif "price match guarantee" in d_lower:
            candidates.append(("Price Match Guarantee", 6))
        elif "lowest price guarantee" in d_lower:
            candidates.append(("Lowest Price Guarantee", 6))
        elif "on-time guarantee" in d_lower:
            candidates.append(("On-Time Guarantee", 5))
        elif "done right guarantee" in d_lower:
            candidates.append(("Done Right Guarantee", 5))
        elif "clean guarantee" in d_lower:
            candidates.append(("Clean Guarantee", 4))
        elif "no hidden fees" in d_lower:
            candidates.append(("No Hidden Fees", 5))
        elif "competitive pricing" in d_lower:
            candidates.append(("Competitive Pricing", 4))
        elif "affordable rates" in d_lower:
            candidates.append(("Affordable Rates", 4))
        elif "senior discounts" in d_lower:
            candidates.append(("Senior Discounts", 4))
        elif "military discounts" in d_lower:
            candidates.append(("Military Discounts", 4))
        elif "free shipping" in d_lower:
            candidates.append(("Free Shipping", 5))
        elif "free delivery" in d_lower:
            candidates.append(("Free Delivery", 5))
        elif "free pickup and delivery" in d_lower:
            candidates.append(("Free Pickup & Delivery", 6))
        elif "fast response" in d_lower:
            candidates.append(("Fast Response", 5))
        elif "quick turnaround" in d_lower:
            candidates.append(("Quick Turnaround", 4))
        elif "weekend availability" in d_lower:
            candidates.append(("Weekend Available", 4))
        elif "evening appointments" in d_lower:
            candidates.append(("Evening Appointments", 4))
        elif "walk-ins welcome" in d_lower:
            candidates.append(("Walk-Ins Welcome", 4))
        elif "no appointment needed" in d_lower:
            candidates.append(("No Appointment Needed", 4))
        elif "we come to you" in d_lower:
            candidates.append(("We Come to You", 4))
        elif "on-site service" in d_lower:
            candidates.append(("On-Site Service", 4))
        elif "virtual consultations" in d_lower:
            candidates.append(("Virtual Consultations", 4))
        elif "easy scheduling" in d_lower:
            candidates.append(("Easy Scheduling", 4))
        elif "flexible scheduling" in d_lower:
            candidates.append(("Flexible Scheduling", 4))
        elif "personalized service" in d_lower:
            candidates.append(("Personalized Service", 4))
        elif "one-stop shop" in d_lower:
            candidates.append(("One-Stop Shop", 4))
        elif "turnkey solutions" in d_lower:
            candidates.append(("Turnkey Solutions", 4))
        elif "stress-free" in d_lower:
            candidates.append(("Stress-Free", 3))
        elif "worry-free" in d_lower:
            candidates.append(("Worry-Free", 3))
        elif "risk-free" in d_lower:
            candidates.append(("Risk-Free", 3))
        elif "no obligation" in d_lower:
            candidates.append(("No Obligation", 4))
        elif "no pressure" in d_lower:
            candidates.append(("No Pressure", 3))
        elif "honest pricing" in d_lower:
            candidates.append(("Honest Pricing", 4))
        elif "fair pricing" in d_lower:
            candidates.append(("Fair Pricing", 4))
        elif "budget-friendly" in d_lower:
            candidates.append(("Budget-Friendly", 3))
        elif "discounts available" in d_lower:
            candidates.append(("Discounts Available", 4))
        elif "referral program" in d_lower:
            candidates.append(("Referral Program", 3))
        elif "loyalty program" in d_lower:
            candidates.append(("Loyalty Program", 3))
        elif "free returns" in d_lower:
            candidates.append(("Free Returns", 4))
        elif "100% satisfaction" in d_lower:
            candidates.append(("100% Satisfaction", 6))
        elif "no-surprise guarantee" in d_lower:
            candidates.append(("No-Surprise Guarantee", 5))
        elif "quality guarantee" in d_lower or "quality guaranteed" in d_lower:
            candidates.append(("Quality Guaranteed", 5))
        elif "results guaranteed" in d_lower:
            candidates.append(("Results Guaranteed", 5))
        elif "best price guarantee" in d_lower:
            candidates.append(("Best Price Guarantee", 6))
        elif "price beat guarantee" in d_lower:
            candidates.append(("Price Beat Guarantee", 5))
        elif "we guarantee" in d_lower:
            candidates.append(("Guaranteed", 4))
        elif "we promise" in d_lower:
            candidates.append(("We Promise", 3))
        elif "energy efficient" in d_lower:
            candidates.append(("Energy Efficient", 4))
        elif "sustainable" in d_lower:
            candidates.append(("Sustainable", 3))
        elif "green business" in d_lower:
            candidates.append(("Green Business", 4))
        elif "multi-generational" in d_lower:
            candidates.append(("Multi-Generational", 5))
        elif "second generation" in d_lower:
            candidates.append(("2nd Generation", 5))
        elif "third generation" in d_lower:
            candidates.append(("3rd Generation", 5))
        elif "fourth generation" in d_lower:
            candidates.append(("4th Generation", 5))
        elif "family-run" in d_lower:
            candidates.append(("Family-Run", 5))
        elif "next-day installation" in d_lower:
            candidates.append(("Next-Day Installation", 5))
        elif "contactless service" in d_lower:
            candidates.append(("Contactless Service", 3))
        elif "curbside pickup" in d_lower:
            candidates.append(("Curbside Pickup", 3))
        elif "tailored solutions" in d_lower:
            candidates.append(("Tailored Solutions", 4))
        elif "membership benefits" in d_lower:
            candidates.append(("Membership Benefits", 3))
        elif "first responder discount" in d_lower:
            candidates.append(("First Responder Discount", 4))

    # Trust signals
    for ts in profile.trust_signals:
        ts_lower = ts.lower()
        if "licensed" in ts_lower:
            candidates.append(("Licensed", 5))
        elif "insured" in ts_lower:
            candidates.append(("Insured", 5))
        elif "bonded" in ts_lower:
            candidates.append(("Bonded", 5))
        elif "bbb accredited" in ts_lower:
            candidates.append(("BBB Accredited", 7))
        elif "bbb a+" in ts_lower:
            candidates.append(("BBB A+ Rated", 7))
        elif "google guaranteed" in ts_lower:
            candidates.append(("Google Guaranteed", 7))
        elif "google screened" in ts_lower:
            candidates.append(("Google Screened", 6))
        elif "award-winning" in ts_lower:
            candidates.append(("Award-Winning", 9))
        elif "5-star" in ts_lower:
            candidates.append(("5-Star Rated", 7))
        elif "star rating" in ts_lower:
            candidates.append(("Top Rated", 6))
        elif "years of experience" in ts_lower:
            candidates.append(("Years of Experience", 6))
        elif "manufacturer certified" in ts_lower:
            candidates.append(("Manufacturer Certified", 6))
        elif "factory certified" in ts_lower:
            candidates.append(("Factory Certified", 6))
        elif "osha certified" in ts_lower:
            candidates.append(("OSHA Certified", 6))
        elif "epa certified" in ts_lower:
            candidates.append(("EPA Certified", 6))
        elif "chamber of commerce" in ts_lower:
            candidates.append(("Chamber of Commerce", 5))
        elif "workers comp" in ts_lower:
            candidates.append(("Workers Comp", 4))
        elif "background checked" in ts_lower:
            candidates.append(("Background Checked", 5))
        elif "drug tested" in ts_lower:
            candidates.append(("Drug Tested", 4))
        elif "leed certified" in ts_lower:
            candidates.append(("LEED Certified", 6))
        elif "energy star certified" in ts_lower:
            candidates.append(("Energy Star Certified", 6))
        elif "b corp certified" in ts_lower:
            candidates.append(("B Corp Certified", 6))
        elif "google rating" in ts_lower:
            candidates.append(("Google Rated", 5))

    # Certifications
    for cert in profile.certifications:
        if len(cert) <= 35:
            candidates.append((cert, 6))

    # Service area — relevant for LOCAL_AUTHORITY
    sa = profile.service_area.strip()
    if sa:
        # Format nicely
        if sa.lower().startswith("greater "):
            candidates.append((f"Serving {sa}", 8))
        else:
            candidates.append((f"Serving {sa}", 7))

    # Location fallback for local
    loc = profile.location.strip()
    if loc and not sa:
        candidates.append((f"Serving {loc}", 6))

    # Deduplicate by text (case-insensitive)
    seen: Set[str] = set()
    unique: List[Tuple[str, int]] = []
    for text, priority in candidates:
        key = text.lower()
        if key not in seen:
            seen.add(key)
            unique.append((text, priority))

    # Sort by priority descending
    unique.sort(key=lambda x: x[1], reverse=True)

    # Return top 1-2 items (just the text)
    return [text for text, _ in unique[:2]]


# ======================================================================
# Strategy eligibility checks
# ======================================================================

def _has_trust_evidence(profile: BrandProfile) -> bool:
    """Check if profile has sufficient evidence for TRUST_LED strategy."""
    if profile.years_in_business.strip():
        return True
    if profile.awards:
        return True
    if profile.certifications:
        return True
    if profile.guarantees:
        return True
    # Trust signals like licensed/insured/bonded
    for ts in profile.trust_signals:
        ts_lower = ts.lower()
        if any(kw in ts_lower for kw in (
            "licensed", "insured", "bonded", "bbb", "award-winning",
            "5-star", "google guaranteed", "google screened",
            "chamber of commerce", "years of experience",
        )):
            return True
    return False


def _has_service_evidence(profile: BrandProfile) -> bool:
    """Check if profile has sufficient evidence for SERVICE_LED strategy."""
    if profile.services:
        return True
    if profile.categories:
        return True
    return False


def _has_offer_evidence(profile: BrandProfile) -> bool:
    """Check if profile has sufficient evidence for OFFER_LED strategy."""
    for d in profile.differentiators:
        d_lower = d.lower()
        if any(kw in d_lower for kw in (
            "free estimates", "free inspection", "free consultation",
            "financing available", "free shipping", "free delivery",
            "discount", "money-back guarantee", "satisfaction guarantee",
            "price match", "lowest price", "best price",
        )):
            return True
    # Also check guarantees for offer-like signals
    for g in profile.guarantees:
        g_lower = g.lower()
        if any(kw in g_lower for kw in (
            "money-back", "satisfaction guarantee", "price match",
            "lowest price", "best price", "price beat",
        )):
            return True
    return False


def _has_local_evidence(profile: BrandProfile) -> bool:
    """Check if profile has sufficient evidence for LOCAL_AUTHORITY strategy."""
    if profile.service_area.strip():
        return True
    if profile.location.strip():
        return True
    return False


def _has_problem_evidence(profile: BrandProfile) -> bool:
    """Check if profile has sufficient evidence for PROBLEM_LED strategy.

    Requires at least one service that maps to a problem frame.
    """
    for svc in profile.services:
        if _problem_frame_for_service(svc):
            return True
    return False


# ======================================================================
# Strategy candidate builders
# ======================================================================

def _build_trust_candidate(profile: BrandProfile) -> Optional[MessageStrategy]:
    """Build a TRUST_LED strategy candidate."""
    if not _has_trust_evidence(profile):
        return None

    evidence: List[str] = []
    primary = ""

    # Build primary message from strongest trust signal
    yib = profile.years_in_business.strip()
    if yib:
        try:
            years = int(yib)
            primary = f"{years} Years of Experience"
            evidence.append("years_in_business")
        except ValueError:
            pass

    if not primary and profile.awards:
        for award in profile.awards:
            if "award-winning" in award.lower():
                primary = "Award-Winning Service"
                evidence.append("awards")
                break
    if not primary and profile.awards:
        primary = "Award-Winning Service"
        evidence.append("awards")

    if not primary and profile.certifications:
        primary = "Certified Professionals"
        evidence.append("certifications")

    if not primary and profile.guarantees:
        for g in profile.guarantees:
            g_lower = g.lower()
            if "workmanship" in g_lower:
                primary = "Workmanship Guaranteed"
                evidence.append("guarantees")
                break
            if "lifetime" in g_lower:
                primary = "Lifetime Warranty"
                evidence.append("guarantees")
                break
            if "satisfaction" in g_lower:
                primary = "Satisfaction Guaranteed"
                evidence.append("guarantees")
                break
        if not primary:
            primary = "Quality Guaranteed"
            evidence.append("guarantees")

    if not primary:
        # Fallback: licensed/insured
        for ts in profile.trust_signals:
            ts_lower = ts.lower()
            if "licensed" in ts_lower and "insured" in ts_lower:
                primary = "Licensed & Insured"
                evidence.append("trust_signals")
                break
        if not primary:
            primary = "Trusted Service"
            evidence.append("trust_signals")

    cta, phone = _select_cta(profile)
    proof = _select_supporting_proof(profile, TRUST_LED)
    # Remove proof that duplicates primary message
    proof = [p for p in proof if p.lower() != primary.lower()]

    score = _score_strategy(profile, TRUST_LED, primary, proof, evidence)
    confidence = _compute_confidence(profile, evidence)

    return MessageStrategy(
        strategy_type=TRUST_LED,
        primary_message=primary,
        supporting_proof=proof[:2],
        cta=cta,
        rationale=_build_rationale(TRUST_LED, evidence),
        score=score,
        evidence=evidence,
        phone=phone,
        confidence=confidence,
    )


def _build_service_candidate(profile: BrandProfile) -> Optional[MessageStrategy]:
    """Build a SERVICE_LED strategy candidate."""
    if not _has_service_evidence(profile):
        return None

    evidence: List[str] = []
    primary = _select_primary_service(profile)
    if primary:
        evidence.append("services")
        # Title-case for display
        primary = primary.title()
    elif profile.categories:
        cat = profile.categories[0]
        primary = cat.title()
        evidence.append("categories")
    else:
        return None

    cta, phone = _select_cta(profile)
    proof = _select_supporting_proof(profile, SERVICE_LED)
    proof = [p for p in proof if p.lower() != primary.lower()]

    score = _score_strategy(profile, SERVICE_LED, primary, proof, evidence)
    confidence = _compute_confidence(profile, evidence)

    return MessageStrategy(
        strategy_type=SERVICE_LED,
        primary_message=primary,
        supporting_proof=proof[:2],
        cta=cta,
        rationale=_build_rationale(SERVICE_LED, evidence),
        score=score,
        evidence=evidence,
        service_focus=primary,
        phone=phone,
        confidence=confidence,
    )


def _build_offer_candidate(profile: BrandProfile) -> Optional[MessageStrategy]:
    """Build an OFFER_LED strategy candidate."""
    if not _has_offer_evidence(profile):
        return None

    evidence: List[str] = []
    primary = ""

    # Find the strongest offer
    for d in profile.differentiators:
        d_lower = d.lower()
        if "free estimates" in d_lower:
            primary = "Free Estimates"
            evidence.append("differentiators")
            break
        if "free inspection" in d_lower:
            primary = "Free Inspections"
            evidence.append("differentiators")
            break
        if "free consultation" in d_lower:
            primary = "Free Consultation"
            evidence.append("differentiators")
            break
        if "financing available" in d_lower:
            primary = "Financing Available"
            evidence.append("differentiators")
            break
        if "free shipping" in d_lower:
            primary = "Free Shipping"
            evidence.append("differentiators")
            break
        if "free delivery" in d_lower:
            primary = "Free Delivery"
            evidence.append("differentiators")
            break

    if not primary:
        for d in profile.differentiators:
            d_lower = d.lower()
            if "money-back guarantee" in d_lower:
                primary = "Money-Back Guarantee"
                evidence.append("differentiators")
                break
            if "satisfaction guarantee" in d_lower:
                primary = "Satisfaction Guarantee"
                evidence.append("differentiators")
                break
            if "price match" in d_lower:
                primary = "Price Match Guarantee"
                evidence.append("differentiators")
                break
            if "lowest price" in d_lower:
                primary = "Lowest Price Guarantee"
                evidence.append("differentiators")
                break
            if "best price" in d_lower:
                primary = "Best Price Guarantee"
                evidence.append("differentiators")
                break
            if "discount" in d_lower:
                primary = "Discounts Available"
                evidence.append("differentiators")
                break

    if not primary:
        for g in profile.guarantees:
            g_lower = g.lower()
            if "money-back" in g_lower:
                primary = "Money-Back Guarantee"
                evidence.append("guarantees")
                break
            if "satisfaction guarantee" in g_lower:
                primary = "Satisfaction Guarantee"
                evidence.append("guarantees")
                break
            if "price match" in g_lower:
                primary = "Price Match Guarantee"
                evidence.append("guarantees")
                break
            if "lowest price" in g_lower:
                primary = "Lowest Price Guarantee"
                evidence.append("guarantees")
                break
            if "best price" in g_lower:
                primary = "Best Price Guarantee"
                evidence.append("guarantees")
                break

    if not primary:
        return None

    cta, phone = _select_cta(profile)
    proof = _select_supporting_proof(profile, OFFER_LED)
    proof = [p for p in proof if p.lower() != primary.lower()]

    score = _score_strategy(profile, OFFER_LED, primary, proof, evidence)
    confidence = _compute_confidence(profile, evidence)

    return MessageStrategy(
        strategy_type=OFFER_LED,
        primary_message=primary,
        supporting_proof=proof[:2],
        cta=cta,
        rationale=_build_rationale(OFFER_LED, evidence),
        score=score,
        evidence=evidence,
        phone=phone,
        confidence=confidence,
    )


def _build_local_candidate(profile: BrandProfile) -> Optional[MessageStrategy]:
    """Build a LOCAL_AUTHORITY strategy candidate."""
    if not _has_local_evidence(profile):
        return None

    evidence: List[str] = []
    geo = profile.service_area.strip() or profile.location.strip()
    if profile.service_area.strip():
        evidence.append("service_area")
    if profile.location.strip():
        evidence.append("location")

    primary = geo
    geographic_focus = geo

    cta, phone = _select_cta(profile)
    proof = _select_supporting_proof(profile, LOCAL_AUTHORITY)
    proof = [p for p in proof if p.lower() != primary.lower()]

    score = _score_strategy(profile, LOCAL_AUTHORITY, primary, proof, evidence)
    confidence = _compute_confidence(profile, evidence)

    return MessageStrategy(
        strategy_type=LOCAL_AUTHORITY,
        primary_message=primary,
        supporting_proof=proof[:2],
        cta=cta,
        rationale=_build_rationale(LOCAL_AUTHORITY, evidence),
        score=score,
        evidence=evidence,
        geographic_focus=geographic_focus,
        phone=phone,
        confidence=confidence,
    )


def _build_problem_candidate(profile: BrandProfile) -> Optional[MessageStrategy]:
    """Build a PROBLEM_LED strategy candidate.

    Only creates a candidate if a verified service maps to a problem frame.
    Does NOT invent problems.
    """
    if not _has_problem_evidence(profile):
        return None

    evidence: List[str] = []
    primary = ""
    service_focus = ""

    # Find the first service that maps to a problem frame
    for svc in profile.services:
        frame = _problem_frame_for_service(svc)
        if frame:
            primary = frame
            service_focus = svc
            evidence.append("services")
            break

    if not primary:
        return None

    cta, phone = _select_cta(profile)
    proof = _select_supporting_proof(profile, PROBLEM_LED)
    proof = [p for p in proof if p.lower() != primary.lower()]

    score = _score_strategy(profile, PROBLEM_LED, primary, proof, evidence)
    confidence = _compute_confidence(profile, evidence)

    return MessageStrategy(
        strategy_type=PROBLEM_LED,
        primary_message=primary,
        supporting_proof=proof[:2],
        cta=cta,
        rationale=_build_rationale(PROBLEM_LED, evidence),
        score=score,
        evidence=evidence,
        service_focus=service_focus,
        phone=phone,
        confidence=confidence,
    )


# ======================================================================
# Scoring
# ======================================================================

def _score_strategy(
    profile: BrandProfile,
    strategy_type: str,
    primary_message: str,
    proof: List[str],
    evidence: List[str],
) -> float:
    """Compute a deterministic score for a strategy candidate.

    Score range: 0.0 – 1.0

    Factors:
        + Base score per strategy type
        + Multiple evidence sources
        + Multiple supporting proof items
        + Strong category/service alignment
        + Explicit customer benefit (offer)
        + Local relevance
        + Concise message length

    Penalties:
        - Weak evidence (single source)
        - Overly generic message
        - Excessively long message (>10 words)
        - Ancillary service focus
    """
    score = 0.0

    # Base score by strategy type
    base_scores = {
        TRUST_LED: 0.50,
        SERVICE_LED: 0.45,
        OFFER_LED: 0.45,
        LOCAL_AUTHORITY: 0.40,
        PROBLEM_LED: 0.35,
    }
    score += base_scores.get(strategy_type, 0.30)

    # Evidence diversity bonus
    evidence_count = len(set(evidence))
    if evidence_count >= 3:
        score += 0.15
    elif evidence_count >= 2:
        score += 0.10
    elif evidence_count >= 1:
        score += 0.05

    # Supporting proof bonus
    if len(proof) >= 2:
        score += 0.10
    elif len(proof) >= 1:
        score += 0.05

    # Category/service alignment
    if profile.categories and profile.services:
        score += 0.05

    # Explicit customer benefit (for OFFER_LED)
    if strategy_type == OFFER_LED:
        score += 0.05

    # Local relevance bonus
    if profile.service_area.strip() or profile.location.strip():
        if strategy_type in (LOCAL_AUTHORITY, TRUST_LED, SERVICE_LED):
            score += 0.05

    # Message length: prefer concise (2-7 words ideal)
    word_count = len(primary_message.split())
    if 2 <= word_count <= 7:
        score += 0.05
    elif word_count > 10:
        score -= 0.10
    elif word_count < 2:
        score -= 0.05

    # Penalty: overly generic message
    generic_messages = {
        "trusted service", "quality service", "professional service",
        "best service", "great service", "reliable service",
    }
    if primary_message.lower() in generic_messages:
        score -= 0.10

    # Penalty: ancillary service focus
    if strategy_type == SERVICE_LED:
        svc_lower = primary_message.lower()
        if svc_lower in _ANCILLARY_SERVICES:
            score -= 0.10

    # Clamp to 0.0-1.0
    return max(0.0, min(1.0, round(score, 2)))


def _compute_confidence(profile: BrandProfile, evidence: List[str]) -> float:
    """Compute confidence in the supporting business evidence.

    Confidence reflects how certain we are that the evidence is reliable,
    based on the number and quality of evidence sources.

    This is distinct from score (which measures strategic strength).
    """
    confidence = 0.0

    # Each evidence source adds confidence
    evidence_set = set(evidence)
    confidence += len(evidence_set) * 0.15

    # Strong evidence types boost confidence
    if "years_in_business" in evidence_set:
        confidence += 0.10
    if "awards" in evidence_set:
        confidence += 0.10
    if "certifications" in evidence_set:
        confidence += 0.08
    if "guarantees" in evidence_set:
        confidence += 0.08
    if "differentiators" in evidence_set:
        confidence += 0.05
    if "services" in evidence_set:
        confidence += 0.05
    if "service_area" in evidence_set:
        confidence += 0.05
    if "location" in evidence_set:
        confidence += 0.03
    if "creative_locality" in evidence_set:
        confidence += 0.04
    if "trust_signals" in evidence_set:
        confidence += 0.05
    if "categories" in evidence_set:
        confidence += 0.03

    return max(0.0, min(1.0, round(confidence, 2)))


def _build_rationale(strategy_type: str, evidence: List[str]) -> str:
    """Build a human-readable rationale for why this strategy was chosen."""
    type_descriptions = {
        TRUST_LED: "Lead with credibility and trust signals",
        SERVICE_LED: "Lead with the core service offering",
        OFFER_LED: "Lead with a concrete customer benefit or offer",
        LOCAL_AUTHORITY: "Lead with geographic relevance and local presence",
        PROBLEM_LED: "Lead with a customer problem the business solves",
    }
    desc = type_descriptions.get(strategy_type, "Strategy based on available evidence")
    evidence_str = ", ".join(evidence) if evidence else "brand profile"
    return f"{desc}. Evidence: {evidence_str}."


# ======================================================================
# Deduplication
# ======================================================================

def _deduplicate_strategies(strategies: List[MessageStrategy]) -> List[MessageStrategy]:
    """Remove substantially equivalent strategies.

    Two strategies are considered duplicates if they have the same
    strategy_type AND the same primary_message (case-insensitive).
    The higher-scored one is kept.
    """
    seen: Dict[Tuple[str, str], MessageStrategy] = {}
    for s in strategies:
        key = (s.strategy_type, s.primary_message.lower())
        if key not in seen or s.score > seen[key].score:
            seen[key] = s
    return list(seen.values())


# ======================================================================
# MessageStrategyEngine
# ======================================================================

class MessageStrategyEngine:
    """Generates message strategy candidates from a BrandProfile.

    Usage::

        engine = MessageStrategyEngine()
        strategies = engine.generate(profile)

    The engine:
    1. Inspects BrandProfile for evidence
    2. Determines which strategy types are supported
    3. Generates candidates for each supported type
    4. Scores each candidate
    5. Sorts strongest → weakest
    6. Deduplicates substantially equivalent strategies
    7. Returns a small candidate set (typically 3-5)

    Does NOT:
    - Modify BrandProfile
    - Call external APIs
    - Use ML/LLM
    - Generate final advertising copy
    """

    def generate(
        self,
        profile: BrandProfile,
        *,
        creative_locality: str = "",
    ) -> List[MessageStrategy]:
        """Generate message strategy candidates for a BrandProfile.

        Args:
            profile: A populated BrandProfile with business intelligence.

        Returns:
            A list of MessageStrategy candidates, sorted by score descending.
            Returns empty list if profile has insufficient evidence.
        """
        if not profile:
            return []

        candidates: List[MessageStrategy] = []

        # Build candidates for each strategy type
        builders = [
            _build_trust_candidate,
            _build_service_candidate,
            _build_offer_candidate,
            _build_local_candidate,
            _build_problem_candidate,
        ]

        for builder in builders:
            candidate = builder(profile)
            if candidate is not None:
                candidates.append(candidate)

        candidates = _inject_localized_variants(
            profile,
            candidates,
            creative_locality,
        )

        # Deduplicate
        candidates = _deduplicate_strategies(candidates)

        # Sort by score descending, then by confidence descending
        candidates.sort(key=lambda s: (s.score, s.confidence), reverse=True)

        return candidates