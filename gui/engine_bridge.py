"""Boundary between the GUI and the existing engine.

The GUI never calls engine modules directly; it goes through this bridge.
"""

from __future__ import annotations

from gui.models.mockup_request import MockupRequest
from gui.models.mockup_result import MockupResult


def generate(request: MockupRequest) -> MockupResult:
    """Generate a mockup for the given request.

    Placeholder: establishes the GUI/engine boundary. Real engine calls
    will be wired in here later.
    """
    return MockupResult()