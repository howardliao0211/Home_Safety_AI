"""Render the code-defined house mark at launcher, splash and favicon sizes.

Run with backend/.venv/bin/python scripts/generate-brand.py (Pillow dependency).
Coordinates use a 256-unit square; supersampling keeps every export crisp.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "mobile" / "assets"
CREAM = "#f7f6f1"
GREEN = "#245c46"


def render(name, size, *, transparent=False, monochrome=False, inset=0):
    scale = 4
    image = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0) if transparent else CREAM)
    draw = ImageDraw.Draw(image)

    def point(x, y):
        return ((inset + x / 256 * (1 - 2 * inset)) * size * scale,
                (inset + y / 256 * (1 - 2 * inset)) * size * scale)

    # Broad roof, sheltered interior and an open doorway; no tiny decoration.
    draw.polygon([point(128, 48), point(36, 126), point(55, 149), point(128, 87),
                  point(201, 149), point(220, 126)], fill="#000000" if monochrome else GREEN)
    draw.rounded_rectangle([point(66, 125), point(190, 211)],
                           radius=12 / 256 * size * scale * (1 - 2 * inset),
                           fill="#000000" if monochrome else GREEN)
    draw.rounded_rectangle([point(109, 153), point(147, 232)],
                           radius=8 / 256 * size * scale * (1 - 2 * inset),
                           fill=(0, 0, 0, 0) if transparent else CREAM)
    image.resize((size, size), Image.Resampling.LANCZOS).save(ASSETS / name)


if __name__ == "__main__":
    render("icon.png", 1024, inset=0.08)
    render("android-icon-foreground.png", 1024, transparent=True, inset=0.19)
    render("android-icon-monochrome.png", 1024, transparent=True, monochrome=True, inset=0.19)
    Image.new("RGB", (1024, 1024), CREAM).save(ASSETS / "android-icon-background.png")
    render("splash-icon.png", 512, transparent=True)
    render("favicon.png", 64, inset=0.04)
