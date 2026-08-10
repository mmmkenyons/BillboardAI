"""Concept card widget for the Sprint 3B workspace gallery.

Displays one saved :class:`engine.ad_concept.AdConcept` (authoritative
structured creative state) with its composition family, strategy type,
headline, proof, CTA, score/confidence, selected state, and an optional
artwork thumbnail. Emits ``clicked`` when the card is selected.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from engine.ad_concept import AdConcept

from gui.widgets.thumbnail_loader import ThumbnailLabel

logger = logging.getLogger(__name__)

# Thumbnail size for concept cards.
_CARD_THUMB_W = 220
_CARD_THUMB_H = 110


class ConceptCard(QFrame):
    """A selectable card for a single AdConcept."""

    clicked = Signal(str)  # concept_id

    def __init__(
        self,
        concept: AdConcept,
        selected: bool = False,
        thumbnail_path: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.concept_id = concept.concept_id
        self._selected = selected
        self.setObjectName("conceptCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._build_ui(concept, thumbnail_path)
        self._apply_selected_style()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self, concept: AdConcept, thumbnail_path: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Thumbnail (artwork when available).
        thumb = ThumbnailLabel(_CARD_THUMB_W, _CARD_THUMB_H, self)
        thumb.set_image_path(thumbnail_path)
        layout.addWidget(thumb, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Family + strategy badges.
        badges = QHBoxLayout()
        fam = QLabel(str(concept.composition_family or "—"), self)
        fam.setObjectName("conceptBadge")
        strat = QLabel(str(concept.strategy_type or "—"), self)
        strat.setObjectName("conceptBadge")
        badges.addWidget(fam)
        badges.addWidget(strat)
        badges.addStretch(1)
        layout.addLayout(badges)

        # Headline.
        headline = QLabel(str(concept.headline or "No headline"), self)
        headline.setObjectName("conceptHeadline")
        headline.setWordWrap(True)
        layout.addWidget(headline)

        # Proof (first line).
        if concept.supporting_proof:
            proof = QLabel(str(concept.supporting_proof[0]), self)
            proof.setObjectName("conceptProof")
            proof.setWordWrap(True)
            layout.addWidget(proof)

        # CTA + score row.
        meta = QHBoxLayout()
        cta = QLabel(f"CTA: {concept.cta or '—'}", self)
        cta.setObjectName("conceptMeta")
        score = QLabel(
            f"Score {concept.score:.2f}  conf {concept.confidence:.2f}",
            self,
        )
        score.setObjectName("conceptMeta")
        meta.addWidget(cta)
        meta.addStretch(1)
        meta.addWidget(score)
        layout.addLayout(meta)

        # Selected indicator.
        self.selected_label = QLabel("", self)
        self.selected_label.setObjectName("conceptSelected")
        layout.addWidget(self.selected_label)

    def _apply_selected_style(self) -> None:
        if self._selected:
            self.setProperty("selected", "true")
            self.selected_label.setText("● SELECTED")
        else:
            self.setProperty("selected", "false")
            self.selected_label.setText("")
        self.style().unpolish(self)
        self.style().polish(self)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.concept_id)
        super().mousePressEvent(event)