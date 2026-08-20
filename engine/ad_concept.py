"""Ad Concept Engine for BillboardAI — Sprint 2E.

Decides HOW a billboard's information should be STRUCTURED VISUALLY:
which elements to use, their visual roles, and their conceptual hierarchy.
It does NOT draw final artwork, place pixels, choose fonts, or crop images.

Architecture:
    WebsiteScraper
        -> BrandAsset normalization
        -> BrandProfile
        -> Business Intelligence
        -> MessageStrategyEngine -> MessageStrategy[]  (WHAT TO SAY)
        -> AdConceptEngine       -> AdConcept[]        (WHAT ELEMENTS + ROLES)
        -> Future Copy Engine                          (HOW TO SAY IT)
        -> Future Artwork Layout Engine                (PIXEL PLACEMENT)
        -> Physical Renderer                           (REAL-WORLD SCENE)

Design principles:
    - Evidence-first: every fact must be traceable to the BrandProfile or the
      source MessageStrategy. Nothing is invented here.
    - Deterministic: no LLM, no ML, no external APIs.
    - Independently maintainable: this module consumes ONLY the public
      MessageStrategy contract and public strategy constants. It never reaches
      into private MessageStrategyEngine internals.
    - Budget-disciplined: billboards are extreme-brevity media; the engine
      SELECTS a small, focused element set rather than copying every fact.

Scope lock: no x/y coordinates, no font sizes, no text wrapping, no bounding
boxes, no cropping, no Pillow/OpenCV drawing. Those belong to the Artwork
Layout Engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from engine.brand_profile import BrandAsset, BrandProfile
from engine.message_strategy import (
    MessageStrategy,
    TRUST_LED,
    SERVICE_LED,
    OFFER_LED,
    PROBLEM_LED,
)
# LOCAL_AUTHORITY names a composition family in this module and a strategy type
# in message_strategy. They share the same string value; alias the strategy
# constant so the two roles stay explicit and unambiguous.
from engine.message_strategy import LOCAL_AUTHORITY as STRATEGY_LOCAL_AUTHORITY


# ======================================================================
# Composition families
# ======================================================================

BRAND_DOMINANT = "BRAND_DOMINANT"
HERO_IMAGE = "HERO_IMAGE"
MESSAGE_DOMINANT = "MESSAGE_DOMINANT"
TRUST_AUTHORITY = "TRUST_AUTHORITY"
LOCAL_AUTHORITY = "LOCAL_AUTHORITY"

COMPOSITION_FAMILIES: Tuple[str, ...] = (
    BRAND_DOMINANT,
    HERO_IMAGE,
    MESSAGE_DOMINANT,
    TRUST_AUTHORITY,
    LOCAL_AUTHORITY,
)


# ======================================================================
# Visual-role levels
# ======================================================================

DOMINANT = "DOMINANT"
PRIMARY = "PRIMARY"
SECONDARY = "SECONDARY"
MINIMAL = "MINIMAL"
HIDDEN = "HIDDEN"

VISUAL_ROLES: Tuple[str, ...] = (DOMINANT, PRIMARY, SECONDARY, MINIMAL, HIDDEN)


# ======================================================================
# AdConcept model
# ======================================================================

@dataclass
class AdConcept:
    """A structured ad concept: which elements to use and their visual roles.

    Represents WHAT ELEMENTS + THEIR VISUAL ROLES, not exact artwork/layout.
    No pixel geometry lives here — that belongs to the Artwork Layout Engine.

    All fields are defaulted so the dataclass can be constructed incrementally
    and deserialized robustly (same convention as MessageStrategy).
    """

    concept_id: str = ""
    composition_family: str = ""
    strategy_type: str = ""

    headline: str = ""
    supporting_proof: List[str] = field(default_factory=list)
    cta: str = ""

    logo_role: str = HIDDEN
    hero_role: str = HIDDEN
    headline_role: str = PRIMARY
    proof_role: str = SECONDARY
    cta_role: str = PRIMARY

    hero_asset: Optional[BrandAsset] = None
    logo_asset: Optional[BrandAsset] = None

    service_focus: str = ""
    geographic_focus: str = ""

    rationale: str = ""
    score: float = 0.0
    confidence: float = 0.0

    source_strategy: Optional[MessageStrategy] = None

    person_facts: Dict[str, Any] = field(default_factory=dict)
    personalization_angle: str = ""
    personalization_basis: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Serialization (forward-compatible, same pattern as BrandProfile)
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary for JSON output.

        Nested BrandAsset / MessageStrategy objects are serialized through
        their own to_dict() (or stored as None when absent).
        """
        return {
            "concept_id": self.concept_id,
            "composition_family": self.composition_family,
            "strategy_type": self.strategy_type,
            "headline": self.headline,
            "supporting_proof": list(self.supporting_proof),
            "cta": self.cta,
            "logo_role": self.logo_role,
            "hero_role": self.hero_role,
            "headline_role": self.headline_role,
            "proof_role": self.proof_role,
            "cta_role": self.cta_role,
            "hero_asset": self.hero_asset.to_dict() if self.hero_asset else None,
            "logo_asset": self.logo_asset.to_dict() if self.logo_asset else None,
            "service_focus": self.service_focus,
            "geographic_focus": self.geographic_focus,
            "rationale": self.rationale,
            "score": self.score,
            "confidence": self.confidence,
            "source_strategy": (
                self.source_strategy.to_dict() if self.source_strategy else None
            ),
            "person_facts": dict(self.person_facts),
            "personalization_angle": self.personalization_angle,
            "personalization_basis": list(self.personalization_basis),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AdConcept":
        """Deserialize from a dictionary.

        Unknown fields are silently ignored (forward-compatible). Missing
        optional fields receive safe defaults. Nested BrandAsset /
        MessageStrategy objects are reconstructed whenever the stored value
        is a dictionary; anything else is treated as absent.
        """
        if not isinstance(data, dict):
            data = {}

        def _str(key: str, default: str = "") -> str:
            value = data.get(key)
            return default if value is None else str(value)

        def _float(key: str, default: float = 0.0) -> float:
            try:
                value = data.get(key)
                return float(value) if value is not None else default
            except (TypeError, ValueError):
                return default

        concept_id = _str("concept_id")
        composition_family = _str("composition_family")
        strategy_type = _str("strategy_type")

        headline = _str("headline")
        raw_proof = data.get("supporting_proof")
        supporting_proof = (
            [str(p) for p in raw_proof] if isinstance(raw_proof, list) else []
        )
        cta = _str("cta")

        logo_role = _str("logo_role", HIDDEN)
        hero_role = _str("hero_role", HIDDEN)
        headline_role = _str("headline_role", PRIMARY)
        proof_role = _str("proof_role", SECONDARY)
        cta_role = _str("cta_role", PRIMARY)

        hero_asset = None
        hero_raw = data.get("hero_asset")
        if isinstance(hero_raw, dict):
            try:
                hero_asset = BrandAsset.from_dict(hero_raw)
            except Exception:
                hero_asset = None

        logo_asset = None
        logo_raw = data.get("logo_asset")
        if isinstance(logo_raw, dict):
            try:
                logo_asset = BrandAsset.from_dict(logo_raw)
            except Exception:
                logo_asset = None

        service_focus = _str("service_focus")
        geographic_focus = _str("geographic_focus")

        rationale = _str("rationale")
        score = _float("score")
        confidence = _float("confidence")

        source_strategy = None
        strat_raw = data.get("source_strategy")
        if isinstance(strat_raw, dict):
            try:
                source_strategy = MessageStrategy.from_dict(strat_raw)
            except Exception:
                source_strategy = None

        person_facts_raw = data.get("person_facts")
        person_facts = dict(person_facts_raw) if isinstance(person_facts_raw, dict) else {}
        personalization_basis_raw = data.get("personalization_basis")
        personalization_basis = [str(v) for v in personalization_basis_raw] if isinstance(personalization_basis_raw, list) else []

        return cls(
            concept_id=concept_id,
            composition_family=composition_family,
            strategy_type=strategy_type,
            headline=headline,
            supporting_proof=supporting_proof,
            cta=cta,
            logo_role=logo_role,
            hero_role=hero_role,
            headline_role=headline_role,
            proof_role=proof_role,
            cta_role=cta_role,
            hero_asset=hero_asset,
            logo_asset=logo_asset,
            service_focus=service_focus,
            geographic_focus=geographic_focus,
            rationale=rationale,
            score=score,
            confidence=confidence,
            source_strategy=source_strategy,
            person_facts=person_facts,
            personalization_angle=_str("personalization_angle"),
            personalization_basis=personalization_basis,
        )



# ======================================================================
# Asset eligibility (deterministic)
# ======================================================================

# Logo thresholds — a structured logo BrandAsset must be large enough to read
# on a billboard and not be a degenerate aspect ratio.
MIN_LOGO_WIDTH = 150
MIN_LOGO_HEIGHT = 50
MIN_LOGO_CONFIDENCE = 0.35
MIN_LOGO_ASPECT_RATIO = 0.15
MAX_LOGO_ASPECT_RATIO = 12.0

# Hero thresholds — a normalized hero image must be substantial enough to
# carry the visual story and broadly landscape-ish.
MIN_HERO_WIDTH = 600
MIN_HERO_HEIGHT = 300
MIN_HERO_CONFIDENCE = 0.35
MIN_HERO_ASPECT_RATIO = 0.5
MAX_HERO_ASPECT_RATIO = 4.0


def _asset_aspect_ratio(asset: BrandAsset) -> float:
    """Return the asset's aspect ratio, computing it when metadata is absent."""
    if asset.aspect_ratio and asset.aspect_ratio > 0:
        return float(asset.aspect_ratio)
    if asset.height and asset.height > 0:
        return asset.width / asset.height
    return 0.0


def _logo_usable(asset: Optional[BrandAsset]) -> bool:
    """Whether a BrandAsset is a usable logo for concept generation.

    Deterministic: dimensions, aspect ratio, and confidence must all be
    acceptable. A missing asset or an unusable one is never treated as valid.
    """
    if asset is None:
        return False
    if asset.width < MIN_LOGO_WIDTH or asset.height < MIN_LOGO_HEIGHT:
        return False
    if asset.confidence < MIN_LOGO_CONFIDENCE:
        return False
    ar = _asset_aspect_ratio(asset)
    if ar <= 0:
        return False
    return MIN_LOGO_ASPECT_RATIO <= ar <= MAX_LOGO_ASPECT_RATIO


def _hero_usable(asset: Optional[BrandAsset]) -> bool:
    """Whether a BrandAsset is a usable hero for the HERO_IMAGE family."""
    if asset is None:
        return False
    if asset.width < MIN_HERO_WIDTH or asset.height < MIN_HERO_HEIGHT:
        return False
    if asset.confidence < MIN_HERO_CONFIDENCE:
        return False
    ar = _asset_aspect_ratio(asset)
    if ar <= 0:
        return False
    return MIN_HERO_ASPECT_RATIO <= ar <= MAX_HERO_ASPECT_RATIO


def _best_hero(profile: BrandProfile) -> Optional[BrandAsset]:
    """Pick the best usable hero from the profile's normalized hero assets.

    IMPORTANT: only BrandProfile.hero_assets counts. hero_url is provenance
    metadata, NOT proof that a normalized hero asset exists — it is never used
    to fabricate a hero.
    """
    candidates = [a for a in profile.hero_assets if _hero_usable(a)]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda a: (
            a.selection_score,
            a.quality_score,
            a.width * a.height,
            a.confidence,
        ),
    )


# ======================================================================
# Family / strategy compatibility
# ======================================================================

# Ordered preference list per strategy type (highest compatibility first).
# Used both to order candidate generation and to score family/strategy fit.
# Derived from the general rules in the Sprint 2E spec — not absolute where a
# deterministic improvement was justified (asset availability gates HERO_IMAGE
# at generation time, not here).
FAMILY_COMPATIBILITY: Dict[str, Tuple[str, ...]] = {
    TRUST_LED: (TRUST_AUTHORITY, BRAND_DOMINANT),
    STRATEGY_LOCAL_AUTHORITY: (LOCAL_AUTHORITY, BRAND_DOMINANT),
    PROBLEM_LED: (MESSAGE_DOMINANT, HERO_IMAGE),
    SERVICE_LED: (HERO_IMAGE, BRAND_DOMINANT, MESSAGE_DOMINANT),
    OFFER_LED: (MESSAGE_DOMINANT, BRAND_DOMINANT),
}


# ======================================================================
# Roles and hierarchy per family
# ======================================================================

# Visual roles per family. These describe prominence/hierarchy, not layout.
_FAMILY_ROLES: Dict[str, Dict[str, str]] = {
    BRAND_DOMINANT: {
        "logo": DOMINANT,
        "hero": HIDDEN,
        "headline": PRIMARY,
        "proof": SECONDARY,
        "cta": PRIMARY,
    },
    HERO_IMAGE: {
        "logo": PRIMARY,
        "hero": DOMINANT,
        "headline": PRIMARY,
        "proof": MINIMAL,
        "cta": PRIMARY,
    },
    MESSAGE_DOMINANT: {
        "logo": PRIMARY,
        "hero": HIDDEN,
        "headline": DOMINANT,
        "proof": MINIMAL,
        "cta": PRIMARY,
    },
    TRUST_AUTHORITY: {
        "logo": DOMINANT,
        "hero": HIDDEN,
        "headline": PRIMARY,
        "proof": PRIMARY,
        "cta": SECONDARY,
    },
    LOCAL_AUTHORITY: {
        "logo": DOMINANT,
        "hero": HIDDEN,
        "headline": PRIMARY,
        "proof": SECONDARY,
        "cta": SECONDARY,
    },
}

# Conceptual hierarchy strings used in rationale text (informational only).
_FAMILY_HIERARCHY: Dict[str, str] = {
    BRAND_DOMINANT: "LOGO > HEADLINE > PROOF > CTA",
    HERO_IMAGE: "HERO IMAGE > LOGO > HEADLINE > CTA > optional proof",
    MESSAGE_DOMINANT: "VERY LARGE HEADLINE > LOGO > CTA > minimal proof",
    TRUST_AUTHORITY: "LOGO > TRUST MESSAGE > PROOF > CTA",
    LOCAL_AUTHORITY: "LOGO > LOCAL MESSAGE > SERVICE/PROOF > CTA",
}

# Maximum number of supporting-proof items per family (billboards = brevity).
_PROOF_BUDGET: Dict[str, int] = {
    BRAND_DOMINANT: 2,
    HERO_IMAGE: 1,
    MESSAGE_DOMINANT: 1,
    TRUST_AUTHORITY: 2,
    LOCAL_AUTHORITY: 2,
}

# Families whose hierarchy is led by the logo (drives score/confidence).
_LOGO_LED_FAMILIES = (BRAND_DOMINANT, TRUST_AUTHORITY, LOCAL_AUTHORITY)

# Families that use the logo as a supporting (non-hidden) element when usable.
_LOGO_SUPPORTING_FAMILIES = (HERO_IMAGE, MESSAGE_DOMINANT)

# Proof-relevance keyword groups used to order strategy proof by family.
_TRUST_PROOF_KEYWORDS = (
    "year", "award", "certif", "guarantee", "warranty", "licensed",
    "insured", "bonded", "bbb", "star", "accredit",
)
_OFFER_PROOF_KEYWORDS = (
    "free", "financing", "estimate", "discount", "consultation", "inspection",
)



# ======================================================================
# Family eligibility
# ======================================================================

def _family_eligible(
    family: str,
    strategy: MessageStrategy,
    logo: Optional[BrandAsset],
    hero: Optional[BrandAsset],
) -> Tuple[bool, str]:
    """Whether a family is currently producible for the given strategy.

    Returns (eligible, reason). Families are rejected only when a truthful
    concept cannot be formed without fabricating an asset or a claim.
    """
    if family == BRAND_DOMINANT:
        if logo is None:
            return False, "no usable logo asset for a brand-dominant concept"
        return True, ""
    if family == HERO_IMAGE:
        if hero is None:
            return False, "no usable normalized hero asset (hero_url alone is insufficient)"
        return True, ""
    if family == TRUST_AUTHORITY:
        if strategy.strategy_type != TRUST_LED:
            return False, "trust-authority family requires a trust-led strategy"
        return True, ""
    if family == LOCAL_AUTHORITY:
        if strategy.strategy_type != STRATEGY_LOCAL_AUTHORITY:
            return False, "local-authority family requires a local-authority strategy"
        if not (strategy.geographic_focus or "").strip():
            return False, "local strategy carries no geographic focus"
        return True, ""
    if family == MESSAGE_DOMINANT:
        if not (strategy.primary_message or "").strip():
            return False, "message-dominant family requires a primary message"
        return True, ""
    return False, f"unknown composition family {family!r}"


# ======================================================================
# Proof selection
# ======================================================================

def _is_geo_covered(pool: List[str], geographic_focus: str) -> bool:
    """Whether any existing proof item already carries the geographic focus."""
    geo = (geographic_focus or "").lower()
    if not geo:
        return True  # nothing to add, trivially covered
    return any(geo in (p or "").lower() for p in pool)


def _order_proof_for_family(
    pool: List[str],
    family: str,
    strategy: MessageStrategy,
) -> List[str]:
    """Stable-reorder strategy proof by family relevance (no new text created)."""
    if len(pool) <= 1 or family not in (TRUST_AUTHORITY, LOCAL_AUTHORITY, MESSAGE_DOMINANT):
        return list(pool)

    if family == TRUST_AUTHORITY:
        def _rel(item: str) -> int:
            low = (item or "").lower()
            return 0 if any(k in low for k in _TRUST_PROOF_KEYWORDS) else 1

    elif family == MESSAGE_DOMINANT:
        def _rel(item: str) -> int:
            low = (item or "").lower()
            return 0 if any(k in low for k in _OFFER_PROOF_KEYWORDS) else 1

    else:  # LOCAL_AUTHORITY
        geo_tokens = {
            w for w in ((strategy.geographic_focus or "").lower().split())
            if len(w) > 3
        }

        def _rel(item: str) -> int:
            low = (item or "").lower()
            if "serving" in low or any(t in low for t in geo_tokens):
                return 0
            if any(k in low for k in _TRUST_PROOF_KEYWORDS):
                return 1
            return 2

    return [item for _, item in sorted(enumerate(pool), key=lambda p: (_rel(p[1]), p[0]))]



# Profile-evidence proofs aligned to strategy type (spec: proof must complement
# the strategy and exist in BrandProfile or MessageStrategy evidence).
_OFFER_GUARANTEE_KEYWORDS = (
    "money-back", "price match", "satisfaction", "lowest price", "best price",
)


def _offer_proofs(profile: BrandProfile) -> List[str]:
    """Offer-specific proofs from the profile's differentiators/guarantees."""
    out: List[str] = []
    for item in profile.differentiators:
        low = item.lower()
        if any(k in low for k in _OFFER_PROOF_KEYWORDS):
            out.append(item)
    for item in profile.guarantees:
        low = item.lower()
        if any(k in low for k in _OFFER_GUARANTEE_KEYWORDS):
            out.append(item)
    return out


def _service_proofs(profile: BrandProfile) -> List[str]:
    """Service-specific proofs: a concise primary-service summary + guarantees."""
    out: List[str] = []
    primary = [s.strip() for s in profile.services if (s or "").strip()][:2]
    if primary:
        out.append(" & ".join(primary).title())
    for item in profile.guarantees:
        out.append(item)
    return out


def _trust_proofs(profile: BrandProfile) -> List[str]:
    """Trust-specific proofs: years, awards, certifications, guarantees."""
    out: List[str] = []
    if (profile.years_in_business or "").strip():
        out.append(f"{profile.years_in_business} Years in Business")
    out.extend(a for a in profile.awards if (a or "").strip())
    out.extend(c for c in profile.certifications if (c or "").strip())
    out.extend(g for g in profile.guarantees if (g or "").strip())
    return out


def _merge_unique(base: List[str], additions: List[str]) -> List[str]:
    """Return base then additions, de-duplicated (case-insensitive)."""
    seen: set = set()
    result: List[str] = []
    for item in list(base) + list(additions):
        key = (item or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _normalize_text(text: str) -> str:
    """Normalize a string for trivial-equality comparison.

    Lowercases, strips surrounding whitespace, drops punctuation and collapses
    internal whitespace. Used only to catch substantially identical phrasing
    (e.g. the same message repeated as headline and proof) — NOT semantic
    similarity. Deliberately simple and deterministic.
    """
    if not text:
        return ""
    out: List[str] = []
    for ch in str(text).strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != " ":
            out.append(" ")
    return " ".join("".join(out).split())


def _select_concept_proof(
    profile: BrandProfile,
    strategy: MessageStrategy,
    family: str,
) -> List[str]:
    """Select the supporting proof for a concept from VERIFIED evidence.

    Rules:
      - The pool is built from strategy-relevant BrandProfile evidence (offer /
        service / trust) merged with the source strategy's own
        `supporting_proof` (already evidence-backed). Nothing is fabricated.
      - LOCAL_AUTHORITY concepts additionally use the source strategy's
        explicit `geographic_focus` verbatim as the local geographic proof when
        it is not already carried in the pool.
      - Information budget: any candidate substantially identical (after
        normalization) to the concept headline is dropped so the billboard does
        not repeat the same message twice; the next strongest distinct
        evidence-backed proof is selected instead. No replacement is invented.
      - Proof is capped by the family's information budget (0-2 items).
      - PROBLEM_LED sources are capped at a single credibility fact at most.
    """
    st = strategy.strategy_type

    if st == OFFER_LED:
        pool = _offer_proofs(profile)
    elif st == SERVICE_LED:
        pool = _service_proofs(profile)
    elif st == TRUST_LED:
        pool = _trust_proofs(profile)
    elif st == STRATEGY_LOCAL_AUTHORITY:
        pool = _trust_proofs(profile)
    else:  # PROBLEM_LED and anything unsupported fall back to strategy proof
        pool: List[str] = []

    pool = _merge_unique(pool, [p for p in strategy.supporting_proof if (p or "").strip()])

    # LOCAL_AUTHORITY: geography is first-class proof carried by the source
    # strategy. Use it verbatim, leading the local concept's proof.
    if family == LOCAL_AUTHORITY and st == STRATEGY_LOCAL_AUTHORITY:
        geo = (strategy.geographic_focus or "").strip()
        if geo and not _is_geo_covered(pool, geo):
            pool = [geo] + pool

    # Information budget: remove proof candidates that merely echo the concept
    # headline (normalized equality) — the headline already spends that budget.
    headline_norm = _normalize_text(strategy.primary_message)
    if headline_norm:
        pool = [p for p in pool if _normalize_text(p) != headline_norm]

    budget = _PROOF_BUDGET.get(family, 2)
    if st == PROBLEM_LED:
        budget = min(budget, 1)

    ordered = _order_proof_for_family(pool, family, strategy)
    return ordered[:budget]


# ======================================================================
# Scoring & confidence
# ======================================================================

def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _round4(value: float) -> float:
    return round(float(value), 4)


def _score_concept(
    profile: BrandProfile,
    strategy: MessageStrategy,
    family: str,
    logo: Optional[BrandAsset] = None,
    hero: Optional[BrandAsset] = None,
) -> float:
    """Deterministic, explainable concept score in [0, 1].

    Higher is better. Combines strategy quality, family/strategy
    compatibility, asset fit, and evidence strength. A family whose required
    asset is unavailable is penalized strongly (and normally pre-rejected by
    eligibility).
    """
    s_score = _clamp01(strategy.score)
    s_conf = _clamp01(strategy.confidence)

    score = 0.45 * s_score + 0.20 * s_conf

    compat = FAMILY_COMPATIBILITY.get(strategy.strategy_type, ())
    if family in compat:
        score += 0.15 if compat[0] == family else 0.10
    else:
        score -= 0.20

    logo_ok = _logo_usable(logo)
    hero_ok = _hero_usable(hero)

    if family == BRAND_DOMINANT:
        score += 0.08 if logo_ok else -0.30
    elif family == HERO_IMAGE:
        score += 0.10 if hero_ok else -0.30
    elif family == TRUST_AUTHORITY:
        score += 0.05 if logo_ok else -0.05
    elif family == LOCAL_AUTHORITY:
        score += 0.05 if logo_ok else -0.05
    elif family == MESSAGE_DOMINANT:
        if logo_ok:
            score += 0.03

    evidence_count = len(strategy.evidence or [])
    if evidence_count >= 3:
        score += 0.05
    elif evidence_count == 2:
        score += 0.03
    elif evidence_count == 1:
        score += 0.01

    return _round4(_clamp01(score))


def _compute_concept_confidence(
    strategy: MessageStrategy,
    family: str,
    logo: Optional[BrandAsset],
    hero: Optional[BrandAsset],
) -> float:
    """Concept confidence in [0, 1]: strategy confidence adjusted by assets."""
    conf = _clamp01(strategy.confidence)

    if family == HERO_IMAGE:
        conf += 0.04 if hero is not None else -0.20
    if family in _LOGO_LED_FAMILIES:
        conf += 0.03 if logo is not None else -0.05
    if family in _LOGO_SUPPORTING_FAMILIES and logo is not None:
        conf += 0.02

    return _round4(_clamp01(conf))



# ======================================================================
# Concept construction
# ======================================================================

def _build_rationale(
    strategy: MessageStrategy,
    family: str,
    logo: Optional[BrandAsset],
    hero: Optional[BrandAsset],
    proof: List[str],
) -> str:
    parts = [
        f"{family} composition from {strategy.strategy_type} strategy "
        f"(strategy score {strategy.score:.3f}, confidence {strategy.confidence:.3f}).",
        f"Conceptual hierarchy: {_FAMILY_HIERARCHY.get(family, family)}.",
    ]
    if family == HERO_IMAGE and hero is not None:
        parts.append(
            f"Uses hero asset {hero.width}x{hero.height} "
            f"({hero.format or 'image'}, confidence {hero.confidence:.2f})."
        )
    elif family == HERO_IMAGE:
        parts.append("No hero asset available to lead the image.")
    if logo is not None:
        parts.append(f"Uses usable logo asset {logo.width}x{logo.height}.")
    elif family in _LOGO_LED_FAMILIES:
        parts.append("No usable logo asset; concept proceeds without logo prominence.")
    if proof:
        parts.append(f"Supporting proof: {'; '.join(proof)}.")
    return " ".join(parts)


def _build_concept(
    profile: BrandProfile,
    strategy: MessageStrategy,
    family: str,
    logo: Optional[BrandAsset],
    hero: Optional[BrandAsset],
) -> AdConcept:
    """Construct a single AdConcept from a strategy + family (no mutation)."""
    roles = _FAMILY_ROLES[family]

    logo_role = roles["logo"]
    logo_asset = logo if logo is not None else None
    if logo is None and logo_role != HIDDEN:
        logo_role = HIDDEN
        logo_asset = None

    hero_role = roles["hero"]
    hero_asset = hero if (family == HERO_IMAGE and hero is not None) else None
    if hero is None and hero_role != HIDDEN:
        hero_role = HIDDEN
        hero_asset = None

    proof = _select_concept_proof(profile, strategy, family)

    cta_role = roles["cta"]
    # Phone-driven call CTAs deserve prominence (evidence-based, not invented).
    if cta_role == SECONDARY and (strategy.phone or "").strip():
        cta_role = PRIMARY

    score = _score_concept(profile, strategy, family, logo=logo, hero=hero)
    confidence = _compute_concept_confidence(strategy, family, logo, hero)
    rationale = _build_rationale(strategy, family, logo, hero, proof)

    headline = profile.personalized_headline or strategy.primary_message
    cta = profile.personalized_cta or strategy.cta

    return AdConcept(
        concept_id="",
        composition_family=family,
        strategy_type=strategy.strategy_type,
        headline=headline,
        supporting_proof=list(proof),
        cta=cta,
        logo_role=logo_role,
        hero_role=hero_role,
        headline_role=roles["headline"],
        proof_role=roles["proof"],
        cta_role=cta_role,
        hero_asset=hero_asset,
        logo_asset=logo_asset,
        service_focus=strategy.service_focus,
        geographic_focus=strategy.geographic_focus,
        rationale=rationale,
        score=score,
        confidence=confidence,
        source_strategy=strategy,
        person_facts=profile.person_facts.to_dict(),
        personalization_angle=profile.personalization_angle,
        personalization_basis=list(profile.personalization_basis),
    )


def _deduplicate_concepts(concepts: List[AdConcept]) -> List[AdConcept]:
    """Collapse near-equivalent concepts by (strategy_type, composition_family).

    Keeps the highest-scoring candidate per key, preserving first-seen order
    otherwise.
    """
    best: Dict[Tuple[str, str], AdConcept] = {}
    for concept in concepts:
        key = (concept.strategy_type, concept.composition_family)
        existing = best.get(key)
        if existing is None or concept.score > existing.score:
            best[key] = concept
    return [best[k] for k in best]

# ======================================================================
# Diversity-aware selection
# ======================================================================

TARGET_CONCEPT_COUNT = 3
MAX_CONCEPT_COUNT = 5
MIN_SELECT_SCORE = 0.20
_FAMILY_REUSE_PENALTY = 0.10
_STRATEGY_REUSE_PENALTY = 0.12


def _effective_score(
    concept: AdConcept,
    family_counts: Dict[str, int],
    strategy_counts: Dict[str, int],
) -> float:
    """Score discounted by how much this concept repeats an already-picked story."""
    eff = concept.score
    eff -= _FAMILY_REUSE_PENALTY * family_counts.get(concept.composition_family, 0)
    eff -= _STRATEGY_REUSE_PENALTY * strategy_counts.get(concept.strategy_type, 0)
    return eff


def _select_diverse(candidates: List[AdConcept]) -> List[AdConcept]:
    """Greedily pick differ concepts, favoring distinct family/strategy mix.

    Produces `TARGET_CONCEPT_COUNT` normally, may return fewer when candidates
    are weak, and may extend to at most `MAX_CONCEPT_COUNT` only when an extra
    candidate brings both a new family and a new strategy and is strong enough.
    """
    if not candidates:
        return []

    pool = sorted(
        candidates, key=lambda c: (-c.score, -c.confidence, c.strategy_type, c.composition_family)
    )
    selected: List[AdConcept] = []
    family_counts: Dict[str, int] = {}
    strategy_counts: Dict[str, int] = {}

    # Primary pass: greedy toward target. A genuinely strong best pick is always
    # taken even if below the floor; later weak k picks are skipped.
    while pool and len(selected) < TARGET_CONCEPT_COUNT:
        best = max(
            pool,
            key=lambda c: _effective_score(c, family_counts, strategy_counts),
        )
        eff = _effective_score(best, family_counts, strategy_counts)
        if eff < MIN_SELECT_SCORE and len(selected) > 0:
            break
        selected.append(best)
        pool.remove(best)
        family_counts[best.composition_family] = (
            family_counts.get(best.composition_family, 0) + 1
        )
        strategy_counts[best.strategy_type] = (
            strategy_counts.get(best.strategy_type, 0) + 1
        )

    # Secondary pass: only strong, genuinely new (family + strategy) additions.
    best_score = selected[0].score if selected else 0.0
    for concept in pool:
        if len(selected) >= MAX_CONCEPT_COUNT:
            break
        if concept.composition_family in family_counts:
            continue
        if strategy_counts.get(concept.strategy_type, 0) > 0:
            continue
        if best_score and concept.score < 0.85 * best_score:
            continue
        selected.append(concept)
        family_counts[concept.composition_family] = (
            family_counts.get(concept.composition_family, 0) + 1
        )
        strategy_counts[concept.strategy_type] = (
            strategy_counts.get(concept.strategy_type, 0) + 1
        )

    return selected


# ======================================================================
# AdConceptEngine
# ======================================================================

class AdConceptEngine:
    """Generates ranked, diverse ad concepts from a profile + strategies.

    Consumes the public MessageStrategy contract only. It inspects the
    BrandProfile's normalized brand assets, derives compatible composition
    families, builds and scores candidate concepts, deduplicates near
    equivalents, and returns the strongest, most differentiated set.
    """

    def generate(
        self,
        profile: BrandProfile,
        strategies: List[MessageStrategy],
    ) -> List[AdConcept]:
        """Return the strongest, most diverse AdConcept list (normally 3)."""
        if profile is None or not strategies:
            return []

        logo = profile.logo if _logo_usable(profile.logo) else None
        hero = _best_hero(profile)

        candidates: List[AdConcept] = []
        for strategy in strategies:
            if strategy is None or not (strategy.primary_message or "").strip():
                continue
            compat = FAMILY_COMPATIBILITY.get(strategy.strategy_type, ())
            for family in compat:
                eligible, _reason = _family_eligible(family, strategy, logo, hero)
                if not eligible:
                    continue
                candidates.append(_build_concept(profile, strategy, family, logo, hero))

        if not candidates:
            return []

        concepts = _deduplicate_concepts(candidates)
        selected = _select_diverse(concepts)

        # Final ordering: descending score, then confidence; assign stable IDs.
        selected.sort(
            key=lambda c: (-c.score, -c.confidence, c.strategy_type, c.composition_family)
        )
        for index, concept in enumerate(selected, start=1):
            concept.concept_id = f"concept-{index}"

        return selected
