"""Headline extraction for BillboardAI scraper."""

import re
from bs4 import BeautifulSoup


def extract_headline(html):
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(" ", strip=True)
        if text:
            return _normalize_headline(text)

    candidates = []
    for tag in ["h2", "h3", "h4"]:
        for element in soup.find_all(tag):
            text = element.get_text(" ", strip=True)
            if len(text) > 10:
                score = 100 - len(text) / 10
                if any(keyword in text.lower() for keyword in ["specialist", "expert", "service", "solution"]):
                    score += 10
                candidates.append((score, text))

    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return _normalize_headline(candidates[0][1])

    title = soup.title
    if title and title.get_text(strip=True):
        return _normalize_headline(title.get_text(" ", strip=True))

    description = None
    desc_tag = soup.find("meta", attrs={"name": "description"})
    if desc_tag:
        description = desc_tag.get("content")
    if description:
        return _normalize_headline(description)

    return None


def _normalize_headline(text):
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    if "|" in text:
        text = text.split("|")[0]
    if "-" in text and len(text) > 30:
        text = text.split("-")[0]
    return text.strip()
