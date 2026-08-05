from scraper.logo import pick_best_logo


def test_pick_best_logo_prefers_logo_images():
    html = '''
    <html>
      <body>
        <img src="/images/hero.png" alt="hero banner">
        <img src="/images/logo.svg" alt="Company logo" class="site-logo">
      </body>
    </html>
    '''

    best_score, best_url = pick_best_logo(html, "https://example.com")

    assert best_url == "https://example.com/images/logo.svg"
    assert best_score > 100


def test_pick_best_logo_falls_back_to_og_image():
    html = '''
    <html>
      <head>
        <meta property="og:image" content="https://example.com/images/og.png" />
      </head>
      <body>
        <img src="/images/hero.png" alt="hero banner">
      </body>
    </html>
    '''

    best_score, best_url = pick_best_logo(html, "https://example.com")

    assert best_url == "https://example.com/images/og.png"
    assert best_score == 70
