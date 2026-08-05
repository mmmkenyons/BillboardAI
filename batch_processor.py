"""BillboardAI batch processor wrapper."""

import engine.batch_processor as _engine_batch_processor
from engine.scraper.site import WebsiteScraper as _WebsiteScraper
from engine.uploader import upload_asset as _upload_asset

WebsiteScraper = _WebsiteScraper
upload_asset = _upload_asset

def run_batch(batch_file, output_csv, template="contractor", upload=False):
    _engine_batch_processor.WebsiteScraper = WebsiteScraper
    _engine_batch_processor.upload_asset = upload_asset
    return _engine_batch_processor.run_batch(batch_file, output_csv, template=template, upload=upload)

__all__ = ["run_batch", "WebsiteScraper", "upload_asset"]
