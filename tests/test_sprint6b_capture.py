from __future__ import annotations

from engine.scraper.capture import ScreenshotCaptureService, ScreenshotValidationError
from engine.scraper.validators import ScreenshotQuality


class FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com"
        self.calls: list[tuple] = []

    def goto(self, url, wait_until=None, timeout=None):
        self.calls.append(("goto", wait_until, timeout))

    def screenshot(self, path=None, full_page=True):
        self.calls.append(("screenshot", full_page, path))

    def evaluate(self, script):
        self.calls.append(("evaluate", script))


def test_normal_screenshot_success_unchanged(monkeypatch, tmp_path):
    page = FakePage()
    monkeypatch.setattr("engine.scraper.capture.validate_screenshot", lambda path: ScreenshotQuality(valid=True, score=90))
    result = ScreenshotCaptureService("ok").capture(page, str(tmp_path))
    assert result.strategy_used == "networkidle"
    assert result.retries == 0
    assert any(call[0] == "screenshot" and call[1] is True for call in page.calls)


def test_failed_full_page_uses_bounded_viewport_fallback(monkeypatch, tmp_path):
    page = FakePage()
    outcomes = iter([
        ScreenshotQuality(valid=False, reason="blank_or_low_information", score=0),
        ScreenshotQuality(valid=False, reason="blank_or_low_information", score=0),
        ScreenshotQuality(valid=False, reason="blank_or_low_information", score=0),
        ScreenshotQuality(valid=True, score=80),
    ])
    monkeypatch.setattr("engine.scraper.capture.validate_screenshot", lambda path: next(outcomes))
    result = ScreenshotCaptureService("fallback").capture(page, str(tmp_path))
    assert result.strategy_used == "viewport_fallback"
    assert result.retries == 3
    assert any(call[0] == "screenshot" and call[1] is False for call in page.calls)


def test_invalid_fallback_does_not_bypass_validation(monkeypatch, tmp_path):
    page = FakePage()
    monkeypatch.setattr("engine.scraper.capture.validate_screenshot", lambda path: ScreenshotQuality(valid=False, reason="blank_or_low_information", score=0))
    try:
        ScreenshotCaptureService("bad").capture(page, str(tmp_path))
    except ScreenshotValidationError as exc:
        assert exc.quality is not None
        assert exc.quality.valid is False
        assert len(exc.diagnostics.get("attempts", [])) >= 5
    else:
        raise AssertionError("invalid fallback should not pass")


def test_total_retry_behavior_remains_bounded(monkeypatch, tmp_path):
    page = FakePage()
    monkeypatch.setattr("engine.scraper.capture.validate_screenshot", lambda path: ScreenshotQuality(valid=False, reason="blank_or_low_information", score=0))
    try:
        ScreenshotCaptureService("bounded").capture(page, str(tmp_path))
    except ScreenshotValidationError as exc:
        assert exc.diagnostics.get("max_attempts") == 5
    else:
        raise AssertionError("expected validation failure")