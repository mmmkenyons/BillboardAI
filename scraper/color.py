"""Brand color extraction for BillboardAI scraper."""

from collections import Counter

import numpy as np
from PIL import Image
from sklearn.cluster import KMeans


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*[int(x) for x in rgb])


def extract_brand_colors(image_path, n_colors=5, resize=250):
    if not image_path:
        return []

    try:
        image = Image.open(image_path).convert("RGB")
    except Exception:
        return []

    width, height = image.size
    scale = min(resize / max(width, height), 1.0)
    if scale < 1.0:
        image = image.resize((int(width * scale), int(height * scale)), Image.LANCZOS)

    pixels = np.array(image).reshape(-1, 3)
    if len(pixels) == 0:
        return []

    pixels = pixels[np.all(pixels >= 8, axis=1)]
    if len(pixels) == 0:
        pixels = np.array(image).reshape(-1, 3)

    n_clusters = min(n_colors, len(pixels))
    if n_clusters <= 0:
        return []

    model = KMeans(n_clusters=n_clusters, random_state=0)
    labels = model.fit_predict(pixels)
    palette = [tuple(center) for center in model.cluster_centers_]
    counts = Counter(labels)

    sorted_palette = [palette[idx] for idx, _ in counts.most_common()]
    return [_rgb_to_hex(color) for color in sorted_palette]
