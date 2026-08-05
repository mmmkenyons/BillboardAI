"""BillboardAI analyzer module."""

import cv2
import numpy as np
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _score_copy_candidate(text: str, boost: int = 0) -> int:
    text = _normalize_text(text)
    if len(text) < 15 or len(text) > 140:
        return 0

    score = 50
    score += max(0, 50 - abs(len(text) - 55))

    if any(keyword in text.lower() for keyword in [
        "best",
        "trusted",
        "professional",
        "local",
        "expert",
        "award",
        "specialist",
        "quality",
        "service",
        "solution",
    ]):
        score += 15

    if any(phrase in text for phrase in ["Call", "Book", "Schedule", "Contact", "Get"]):
        score += 10

    score += boost
    if text.endswith("..."):
        score -= 5

    return min(100, max(0, score))


def _quality_label(score: int) -> str:
    if score >= 80:
        return "excellent"
    if score >= 60:
        return "good"
    return "needs improvement"


def extract_ad_copy(html: str, metadata: Dict[str, Any], headline: Optional[str] = None) -> str:
    candidates: List[Tuple[int, str]] = []
    seen: set[str] = set()

    def add_candidate(value: Optional[str], boost: int = 0) -> None:
        if not value:
            return
        normalized = _normalize_text(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append((_score_copy_candidate(normalized, boost), normalized))

    if headline:
        add_candidate(headline, boost=20)

    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        add_candidate(soup.title.string, boost=10)

    for tag in ["h1", "h2", "h3"]:
        for element in soup.find_all(tag):
            add_candidate(element.get_text(" ", strip=True), boost=15 if tag == "h1" else 5)

    description = (
        metadata.get("description")
        or metadata.get("og", {}).get("og:description")
        or metadata.get("twitter", {}).get("twitter:description")
    )
    add_candidate(description)

    og_title = (
        metadata.get("og", {}).get("og:title")
        or metadata.get("twitter", {}).get("twitter:title")
    )
    add_candidate(og_title)

    if not candidates and soup.body:
        for element in soup.body.find_all(["p", "li"]):
            add_candidate(element.get_text(" ", strip=True))

    candidates.sort(key=lambda item: item[0], reverse=True)
    if candidates and candidates[0][0] > 0:
        return candidates[0][1]

    return headline or metadata.get("title") or ""


def _vision_quality_score(image_path: Optional[str]) -> int:
    if not image_path:
        return 0
    path = Path(image_path)
    if not path.exists():
        return 0

    image = cv2.imread(str(path))
    if image is None:
        return 0

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    blur_score = float(lap.var())
    edge = cv2.Canny(gray, 100, 200)
    edge_density = float(np.count_nonzero(edge)) / max(gray.size, 1)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))

    score = 30
    score += min(30, max(0, (blur_score - 100) / 3))
    score += min(25, contrast / 8)
    score += min(15, 150 / max(1, abs(brightness - 120))) if brightness > 0 else 0
    score += min(10, edge_density * 100)

    if brightness < 40 or brightness > 220:
        score -= 10
    if contrast < 15:
        score -= 10

    return min(100, max(0, int(score)))


def score_quality(scrape_data: Dict[str, Any]) -> int:
    score = 0
    if scrape_data.get("headline"):
        score += 20
    if scrape_data.get("ad_copy"):
        score += 20

    logo_score = scrape_data.get("logo_score")
    if isinstance(logo_score, (int, float)):
        score += min(15, max(0, int(logo_score / 7)))

    vision_score = scrape_data.get("vision_score")
    if isinstance(vision_score, (int, float)):
        score += min(20, int(vision_score / 5))

    if scrape_data.get("brand_colors"):
        score += min(10, len(scrape_data["brand_colors"]) * 2)
    if scrape_data.get("hero_url"):
        score += 10
    if scrape_data.get("metadata", {}).get("description"):
        score += 10
    if scrape_data.get("metadata", {}).get("title"):
        score += 10
    if scrape_data.get("asset_paths"):
        score += min(5, len(scrape_data["asset_paths"]))
    if scrape_data.get("css_paths"):
        score += min(5, len(scrape_data["css_paths"]))

    return min(100, score)


def analyze_scrape_data(scrape_data: Dict[str, Any], html: str = "", screenshot_path: Optional[str] = None) -> Dict[str, Any]:
    scrape_data["ad_copy"] = extract_ad_copy(html, scrape_data.get("metadata", {}), scrape_data.get("headline"))
    scrape_data["vision_score"] = _vision_quality_score(screenshot_path)
    scrape_data["vision_label"] = _quality_label(scrape_data["vision_score"])
    scrape_data["quality_score"] = score_quality(scrape_data)
    scrape_data["quality_label"] = _quality_label(scrape_data["quality_score"])
    return scrape_data
