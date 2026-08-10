"""Sprint 2H orchestration layer: AdConcept -> Creative Layout -> physical mockup.

This is the ONLY module that wires the two independently working systems
together:

    SYSTEM A (creative, scene-agnostic):
        AdConcept + BrandProfile
            -> CreativeLayoutEngine.resolve(concept, profile, w, h)
            -> CreativeLayoutSpec
            -> CreativeArtworkRenderer.render(spec)
            -> rectangular PIL artwork

    SYSTEM B (physical, creative-agnostic):
        physical template JSON -> calibrated billboard_quad
        -> perspective warp -> physical-scene mockup

The integration boundary is the RECTANGULAR ARTWORK IMAGE. Neither system is
modified to know about the other:

    - The artwork/layout layer never learns about billboard_quad / scene_path or
      any physical template id.
    - The physical renderer never learns about BrandProfile / MessageStrategy /
      AdConcept. It receives a completed artwork image via
      renderer.render_artwork_into_scene(artwork, scene_template, output_path).

Responsibilities here are limited to orchestration + the template->artwork-size
hand-off. No template ids are hardcoded; every calibrated physical template
(including the two MVP scene templates) resolves through the same code path.
"""
from __future__ import annotations

from typing import Tuple

from engine.ad_concept import AdConcept
from engine.brand_profile import BrandProfile
from engine.layout import CreativeArtworkRenderer, CreativeLayoutEngine, CreativeLayoutSpec
from engine.renderer import renderer as _physical_renderer


def scene_artwork_size(scene_template: str) -> Tuple[int, int]:
    """Return the physical template's intended rectangular artwork (width, height).

    The creative is rendered at exactly these dimensions so the completed
    artwork is never stretched to fit the calibrated quad.

    Raises ValueError when no scene_template is supplied.
    """
    if not scene_template:
        raise ValueError(
            "No scene_template specified — set 'scene_template' to a physical "
            "template id (e.g. a calibrated scene template)."
        )
    return _physical_renderer.artwork_size_for_template(scene_template)


def resolve_concept_spec(
    concept: AdConcept,
    profile: BrandProfile,
    scene_template: str,
) -> CreativeLayoutSpec:
    """Resolve the creative layout spec for a concept at the template's aspect ratio.

    Thin wrapper that reads the physical template's intended artwork dimensions
    and asks the (scene-independent) CreativeLayoutEngine to produce a spec at
    exactly those dimensions.
    """
    width, height = scene_artwork_size(scene_template)
    engine = CreativeLayoutEngine()
    return engine.resolve(concept, profile, width, height)


def render_concept_mockup(
    concept: AdConcept,
    profile: BrandProfile,
    scene_template: str,
    output_path: str,
) -> str:
    """Render a final physical sales mockup for a concept in a physical scene.

    Pipeline:
        1. load physical template -> default_artwork_size
        2. CreativeLayoutEngine.resolve(concept, profile, w, h) -> spec
        3. CreativeArtworkRenderer.render(spec) -> rectangular PIL artwork
        4. physical renderer consumes artwork (in-memory) + perspective-wars
           into the calibrated quad
        5. final mockup saved to output_path

    Returns output_path. The artwork hand-off is fully in-memory — no temporary
    file is written.
    """
    spec = resolve_concept_spec(concept, profile, scene_template)
    artwork = CreativeArtworkRenderer().render(spec)
    return _physical_renderer.render_artwork_into_scene(
        artwork, scene_template, output_path
    )