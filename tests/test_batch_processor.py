import json
import os
from pathlib import Path

import config
from batch_processor import run_batch


def test_run_batch_creates_status_and_csv(tmp_path, monkeypatch):
    batch_file = tmp_path / "urls.txt"
    batch_file.write_text("https://example.com\n")
    output_csv = tmp_path / "smartlead.csv"
    status_file = tmp_path / "batch_status.json"

    monkeypatch.setattr(config, "BATCH_STATUS_FILE", str(status_file))
    monkeypatch.setattr(config, "OUTPUT_FOLDER", str(tmp_path / "output"))

    class FakeScraper:
        def __init__(self, url):
            self.url = url
            self.filename_base = "example"
            self.last_data = {"url": url, "headline": "Test Headline", "company": "Example Co", "metadata": {}}

        def run(self):
            return self.last_data

        def render_billboard(self, template_name, output_path=None):
            output_path = output_path or str(tmp_path / f"{self.filename_base}_{template_name}.png")
            Path(output_path).write_text("fake image")
            return output_path

    import batch_processor

    monkeypatch.setattr(batch_processor, "WebsiteScraper", FakeScraper)
    monkeypatch.setattr(batch_processor, "upload_asset", lambda path, folder="billboardai": f"https://cdn.example.com/{os.path.basename(path)}")

    results = run_batch(str(batch_file), str(output_csv), template="contractor", upload=True)

    assert isinstance(results, dict)
    assert results["https://example.com"]["completed"] is True
    assert output_csv.exists()
    assert status_file.exists()
    with open(status_file, "r", encoding="utf-8") as handle:
        status = json.load(handle)
    assert status["https://example.com"]["completed"] is True


def test_run_batch_resumes_previous_status(tmp_path, monkeypatch):
    batch_file = tmp_path / "urls.txt"
    batch_file.write_text("https://example.com\nhttps://another.com\n")
    output_csv = tmp_path / "smartlead.csv"
    status_file = tmp_path / "batch_status.json"

    monkeypatch.setattr(config, "BATCH_STATUS_FILE", str(status_file))
    monkeypatch.setattr(config, "OUTPUT_FOLDER", str(tmp_path / "output"))

    status = {
        "https://example.com": {"completed": True, "image": "done.png", "upload_url": "https://cdn.example.com/done.png"}
    }
    status_file.write_text(json.dumps(status))

    class FakeScraper:
        def __init__(self, url):
            self.url = url
            self.filename_base = "another"
            self.last_data = {"url": url, "headline": "Another Headline", "company": "Another Co", "metadata": {}}

        def run(self):
            return self.last_data

        def render_billboard(self, template_name, output_path=None):
            output_path = output_path or str(tmp_path / f"{self.filename_base}_{template_name}.png")
            Path(output_path).write_text("fake image")
            return output_path

    monkeypatch.setattr("batch_processor.WebsiteScraper", FakeScraper)
    monkeypatch.setattr("uploader.upload_asset", lambda path, folder="billboardai": f"https://cdn.example.com/{os.path.basename(path)}")

    results = run_batch(str(batch_file), str(output_csv), template="contractor", upload=False)

    assert results["https://example.com"]["completed"] is True
    assert results["https://another.com"]["completed"] is True
    assert output_csv.exists()
