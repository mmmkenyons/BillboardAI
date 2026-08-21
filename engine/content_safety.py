"""Generic website content safety helpers.

These checks identify bot/challenge/interstitial pages before their text or
assets are promoted into billboard creative.  They are deterministic and do not
contain site-specific rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


CHALLENGE_CONTENT_DETECTED = "CHALLENGE_CONTENT_DETECTED"

_CHALLENGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("VERIFY_HUMAN", re.compile(r"\bplease\s+verify\s+you\s+are\s+human\b|\bverify\s+you\s+are\s+human\b", re.I)),
    ("ACCESS_DENIED", re.compile(r"\baccess\s+denied\b|\brequest\s+blocked\b|\bforbidden\b", re.I)),
    ("BROWSER_CHECK", re.compile(r"\bchecking\s+your\s+browser\b|\bjust\s+a\s+moment\b|\bbrowser\s+protection\b", re.I)),
    ("CAPTCHA", re.compile(r"\bcaptcha\b|\brecaptcha\b|\bhcaptcha\b|\bchallenge-platform\b|\bcloudflare\b", re.I)),
    ("SECURITY_INTERSTITIAL", re.compile(r"\bsecurity\s+check\b|\bcomplete\s+the\s+security\s+check\b|\benable\s+javascript\s+and\s+cookies\b", re.I)),
)


@dataclass(frozen=True)
class ChallengeDetection:
    detected: bool = False
    indicators: tuple[str, ...] = field(default_factory=tuple)
    matched_text: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "code": CHALLENGE_CONTENT_DETECTED if self.detected else "",
            "indicators": list(self.indicators),
            "matched_text": list(self.matched_text),
        }


def detect_challenge_content(*values: object) -> ChallengeDetection:
    indicators: list[str] = []
    matched: list[str] = []
    for value in values:
        text = str(value or "")
        if not text.strip():
            continue
        sample = re.sub(r"\s+", " ", text).strip()
        for code, pattern in _CHALLENGE_PATTERNS:
            hit = pattern.search(sample)
            if not hit:
                continue
            if code not in indicators:
                indicators.append(code)
            snippet = sample[max(0, hit.start() - 40): hit.end() + 40]
            if snippet not in matched:
                matched.append(snippet[:180])
    return ChallengeDetection(bool(indicators), tuple(indicators), tuple(matched))


def is_challenge_content(*values: object) -> bool:
    return detect_challenge_content(*values).detected