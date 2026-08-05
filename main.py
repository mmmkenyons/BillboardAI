"""BillboardAI main entry point."""

import argparse
import json
import os

import config
from batch_processor import run_batch
from scraper.site import WebsiteScraper


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BillboardAI scraper or batch processor.")
    parser.add_argument("url", nargs="?", default=None, help="Website URL to scrape")
    parser.add_argument("--template", default="contractor", choices=["contractor", "dentist", "realtor", "auto"], help="Billboard template to use")
    parser.add_argument("--render", action="store_true", help="Render a billboard image after scraping")
    parser.add_argument("--output-image", default=None, help="Path to save the rendered billboard PNG")
    parser.add_argument("--batch-file", default=None, help="Path to a text file containing URLs to process in batch")
    parser.add_argument("--output-csv", default=None, help="Path to save Smartlead CSV for batch processing")
    parser.add_argument("--upload", action="store_true", help="Upload generated images during batch processing")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.batch_file:
        if not args.output_csv:
            raise ValueError("--output-csv is required when using --batch-file")
        results = run_batch(args.batch_file, args.output_csv, template=args.template, upload=args.upload)
        print(json.dumps(results, indent=2))
        return

    if not args.url:
        raise ValueError("A URL is required unless --batch-file is used")

    scraper = WebsiteScraper(args.url)
    result = scraper.run()
    print(json.dumps(result, indent=2))

    if args.render or args.output_image:
        output_image = args.output_image or os.path.join(
            config.IMAGE_FOLDER, f"{scraper.filename_base}_{args.template}.png"
        )
        rendered_path = scraper.render_billboard(args.template, output_image)
        print(f"Rendered billboard image: {rendered_path}")


if __name__ == "__main__":
    main()
