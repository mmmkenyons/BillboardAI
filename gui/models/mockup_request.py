"""Data model describing a mockup generation request."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MockupRequest:
    """A request to generate a billboard mockup.

    Fields are intentionally simple placeholders; the engine bridge will
    consume this model once the GUI pipeline is wired up.
    """

    url: str = ""
    template: str = ""
    output_folder: str = ""
    options: dict = field(default_factory=dict)