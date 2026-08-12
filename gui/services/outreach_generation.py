"""Deterministic, customer-safe cold email generation for campaign export.

This module is intentionally separate from the billboard message-strategy engine.
It generates short outbound email copy from an explicit safe personalization
boundary using only facts suitable for customer-facing outreach.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class OutreachPersonalizationContext:
    first_name: str = ""
    contact_name: str = ""
    company_name: str = ""
    website: str = ""
    category: str = ""
    prospect_city: str = ""
    prospect_state: str = ""
    headline: str = ""
    cta: str = ""
    template: str = ""
    personalization_location: str = ""
    opportunity_city: str = ""
    opportunity_state: str = ""
    placement_name: str = ""
    placement_type: str = ""
    retailer_name: str = ""


@dataclass(frozen=True)
class ProspectOutreachMessage:
    subject: str
    body: str
    opening_line: str
    personalization_basis: str
    generated_at: str


class OutreachGenerationService:
    """Generate short deterministic outreach from customer-safe facts only."""

    _DEFAULT_CTA = "Worth sending it over?"
    _CATEGORY_LABELS = {
        "roofing": "your roofing brand",
        "roofing contractor": "your roofing brand",
        "dentist": "your practice",
        "dental": "your practice",
        "cosmetic dentist": "your practice",
        "realtor": "your real estate brand",
        "real estate": "your real estate brand",
        "real estate agent": "your real estate brand",
    }
    _PLACEMENT_LABELS = {
        "cart_corral": "cart-corral placement",
        "storefront": "storefront placement",
        "entrance": "entrance placement",
    }

    def generate_message(self, context: OutreachPersonalizationContext) -> ProspectOutreachMessage:
        company = _clean(context.company_name)
        if not company:
            raise ValueError("Company name is required for outreach generation")

        opening = self._opening_line(context)
        body = self._body(context, opening)
        subject = f"Quick idea for {company}"
        return ProspectOutreachMessage(
            subject=subject,
            body=body,
            opening_line=opening,
            personalization_basis=self._personalization_basis(context),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def format_placement_type(self, placement_type: str) -> str:
        value = _clean(placement_type).lower()
        if not value:
            return ""
        if value in self._PLACEMENT_LABELS:
            return self._PLACEMENT_LABELS[value]
        return f"{value.replace('_', '-')} placement"

    def _opening_line(self, context: OutreachPersonalizationContext) -> str:
        first_name = _clean(context.first_name)
        if first_name:
            return f"{first_name} —"
        return "Hi —"

    def _body(self, context: OutreachPersonalizationContext, opening: str) -> str:
        company = _clean(context.company_name)
        noun = self._brand_noun(context)
        locality = _clean(context.personalization_location) or _clean(context.opportunity_city)
        placement = self.format_placement_type(context.placement_type)

        if locality:
            first_paragraph = (
                f"{opening} I put together a billboard concept for {company} "
                f"showing how {noun} could look in front of shoppers in {locality}."
            )
        else:
            first_paragraph = (
                f"{opening} I put together a billboard concept for {company} "
                f"and thought you might want to see it."
            )

        paragraphs = [first_paragraph]

        if placement:
            paragraphs.append(f"I mocked it up for a {placement} there.")

        paragraphs.append(self._DEFAULT_CTA)
        return "\n\n".join(paragraphs)

    def _brand_noun(self, context: OutreachPersonalizationContext) -> str:
        category = _clean(context.category).lower()
        return self._CATEGORY_LABELS.get(category, "your brand")

    def _personalization_basis(self, context: OutreachPersonalizationContext) -> str:
        parts: list[str] = []
        if _clean(context.company_name):
            parts.append("company")
        if _clean(context.personalization_location) or _clean(context.opportunity_city):
            parts.append("location")
        if _clean(context.placement_type):
            parts.append("placement")
        if _clean(context.category):
            parts.append("category")
        if not parts:
            return "company"
        return ", ".join(parts)


def _clean(value: object) -> str:
    return str(value or "").strip()