"""BillboardAI main entry point."""

import argparse
import json
import os

import config
from scraper.site import WebsiteScraper


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BillboardAI scraper for a URL.")
    parser.add_argument("url", nargs="?", default="https://www.example.com", help="Website URL to scrape")
    parser.add_argument("--template", default="contractor", choices=["contractor", "dentist", "realtor"], help="Billboard template to use")
    parser.add_argument("--render", action="store_true", help="Render a billboard image after scraping")
    parser.add_argument("--output-image", default=None, help="Path to save the rendered billboard PNG")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
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
