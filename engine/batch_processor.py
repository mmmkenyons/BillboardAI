import json
import os
from pathlib import Path
from typing import Any, Dict, List

import config
from scraper.site import WebsiteScraper
from smartlead import build_lead_entry
from uploader import upload_asset


def _log(message: str) -> None:
    print(f"[Batch] {message}")


def _load_batch_urls(batch_file: str) -> List[str]:
    with open(batch_file, "r", encoding="utf-8-sig") as handle:
        return [line.strip() for line in handle if line.strip()]


def _load_status() -> Dict[str, Any]:
    if os.path.exists(config.BATCH_STATUS_FILE):
        with open(config.BATCH_STATUS_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def _save_status(status: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(config.BATCH_STATUS_FILE), exist_ok=True)
    with open(config.BATCH_STATUS_FILE, "w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2)


def run_batch(batch_file: str, output_csv: str, template: str = "contractor", upload: bool = False) -> Dict[str, Any]:
    os.makedirs(config.OUTPUT_FOLDER, exist_ok=True)
    urls = _load_batch_urls(batch_file)
    status = _load_status()
    entries = []
    results = {}

    _log(f"Starting batch for {len(urls)} URL(s)")

    for url in urls:
        _log(f"Processing: {url}")
        if status.get(url, {}).get("completed"):
            _log(f"Skipping completed URL: {url}")
            results[url] = status[url]
            continue

        try:
            scraper = WebsiteScraper(url)
            data = scraper.run()
            image_path = scraper.render_billboard(template)
            upload_url = None
            if upload:
                _log(f"Uploading image for {url}")
                upload_url = upload_asset(image_path)

            entry = build_lead_entry(data)
            entries.append(entry)

            status[url] = {
                "completed": True,
                "image": image_path,
                "upload_url": upload_url,
            }
            _save_status(status)
            results[url] = status[url]
            _log(f"Completed: {url}")
        except Exception as exc:
            status[url] = {
                "completed": False,
                "error": str(exc),
            }
            _save_status(status)
            results[url] = status[url]
            _log(f"Failed: {url} -> {exc}")

    if entries:
        from smartlead import write_csv
        write_csv(entries, output_csv)
        _log(f"Smartlead CSV written: {output_csv}")

    _log("Batch finished")
    return results
