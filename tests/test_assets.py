import pytest

from scraper.assets import discover_assets


def test_discover_assets_extracts_images_and_css_urls():
    html = '''
    <html>
      <head>
        <link rel="icon" href="/favicon.ico">
        <style>body { background-image: url('/images/bg.png'); }</style>
      </head>
      <body>
        <img src="/images/photo.jpg" data-src="/images/placeholder.jpg">
        <img srcset="/images/1x.png 1x, /images/2x.png 2x">
        <source srcset="/images/video-poster.png 1x, /images/video-poster@2x.png 2x">
      </body>
    </html>
    '''

    urls = discover_assets(html, "https://example.com")
    assert "https://example.com/favicon.ico" in urls
    assert "https://example.com/images/bg.png" in urls
    assert "https://example.com/images/photo.jpg" in urls
    assert "https://example.com/images/placeholder.jpg" in urls
    assert "https://example.com/images/1x.png" in urls
    assert "https://example.com/images/2x.png" in urls
    assert "https://example.com/images/video-poster.png" in urls
    assert "https://example.com/images/video-poster@2x.png" in urls
