from scraper.color import extract_brand_colors


def test_extract_brand_colors_returns_hex_palette(tmp_path):
    from PIL import Image

    image_path = tmp_path / "sample.png"
    image = Image.new("RGB", (100, 100), color=(200, 100, 50))
    image.save(image_path)

    palette = extract_brand_colors(str(image_path), n_colors=3)

    assert isinstance(palette, list)
    assert palette[0].startswith("#")
    assert len(palette) <= 3
