"""BillboardAI smartlead module."""

import csv
import os
from typing import Dict, Optional

import config


def build_lead_entry(scrape_data: Dict[str, any]) -> Dict[str, Optional[str]]:
    headline = scrape_data.get("ad_copy") or scrape_data.get("headline") or scrape_data.get("metadata", {}).get("description") or ""
    company = scrape_data.get("company") or scrape_data.get("metadata", {}).get("title") or ""
    website = scrape_data.get("url")

    first_name = ""
    last_name = ""
    if company:
        parts = company.split()
        first_name = parts[0] if parts else ""
        last_name = parts[-1] if len(parts) > 1 else ""

    return {
        "First Name": first_name,
        "Last Name": last_name,
        "Email": "",
        "Company": company,
        "Website": website,
        "Custom_Image": scrape_data.get("logo_path") or scrape_data.get("hero_path") or "",
        "Headline": headline,
        "Quality Score": str(scrape_data.get("quality_score", "")),
        "Quality Label": scrape_data.get("quality_label", ""),
        "Vision Score": str(scrape_data.get("vision_score", "")),
        "Vision Label": scrape_data.get("vision_label", ""),
    }


def write_csv(entries: list[Dict[str, Optional[str]]], output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=config.SMARTLEAD_FIELDS)
        writer.writeheader()
        writer.writerows(entries)
    return output_path
