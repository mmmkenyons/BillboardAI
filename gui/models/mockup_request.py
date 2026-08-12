"""Data model describing a mockup generation request."""

from __future__ import annotations

from dataclasses import dataclass, field

from gui.models.prospect_generation import OpportunityGenerationContext


@dataclass
class MockupRequest:
    """A request to generate a billboard mockup.

    The controller owns project directories. ``output_path`` is the exact
    PNG path the engine bridge must write — the bridge never invents a
    project folder.
    """

    url: str = ""
    template: str = ""
    output_folder: str = ""
    # Exact destination for the rendered PNG (required for generate()).
    output_path: str = ""
    options: dict = field(default_factory=dict)
    # Extra data for flags like is_new_concept (Sprint 4B Phase E1, no behavior change).
    extra: dict = field(default_factory=dict)
    opportunity_context: OpportunityGenerationContext | None = None
