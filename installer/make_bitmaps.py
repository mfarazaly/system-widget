"""Generate the WiX installer bitmaps (dark theme, matching the widget).

Run from the repo root:   py installer/make_bitmaps.py

Produces:
    installer/banner.bmp   493 x 58   - top strip of the installer dialogs
    installer/dialog.bmp   493 x 312  - left panel of the welcome / finish dialogs
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent


def widget_version() -> str:
    """Version shown in the dialog artwork, taken from the widget itself."""
    try:
        text = (HERE.parent / "SystemWidget.pyw").read_text(encoding="utf-8")
    except OSError:
        return "1.0"
    match = re.search(r'^VERSION = "([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "1.0"

BG_TOP = (16, 19, 26)
BG_BOTTOM = (8, 10, 14)
ACCENTS = [(76, 154, 255), (176, 124, 255), (45, 212, 167)]
TEXT = (232, 237, 246)
DIM = (110, 120, 140)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "seguisb.ttf" if bold else "segoeui.ttf"
    for candidate in (Path(r"C:\Windows\Fonts") / name, Path(r"C:\Windows\Fonts\arial.ttf")):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def gradient(width: int, height: int) -> Image.Image:
    img = Image.new("RGB", (width, height), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(1, height - 1)
        colour = tuple(
            round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)
        )
        draw.line([(0, y), (width, y)], fill=colour)
    return img


def bars(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0) -> None:
    """The little three-bar logo used in the widget's About card."""
    widths = (14, 20, 10)
    for index, (width, colour) in enumerate(zip(widths, ACCENTS)):
        top = y + index * 6 * scale
        draw.rounded_rectangle(
            [x, top, x + width * scale, top + 3.4 * scale],
            radius=1.7 * scale,
            fill=colour,
        )


def make_banner() -> None:
    """Light strip behind the window title of every installer dialog.

    Windows Installer draws its own black title ("Installing System Widget",
    "Welcome to the ... Setup Wizard", ...) into this strip starting about
    27 px from the left edge.  So the image must not contain any text - a
    baked-in product name would be printed straight through the title.  Only
    the small logo is drawn, ending well before that text starts.
    """
    width, height = 493, 58
    img = Image.new("RGB", (width, height), (247, 248, 251))
    draw = ImageDraw.Draw(img)

    # a soft vertical fade so the strip does not look flat
    for y in range(height):
        t = y / (height - 1)
        colour = (round(250 - 6 * t), round(251 - 6 * t), round(253 - 5 * t))
        draw.line([(0, y), (width, y)], fill=colour)

    bars(draw, 6, 22, 0.6)

    draw.line([(0, height - 1), (width, height - 1)], fill=(214, 219, 228), width=1)

    img.save(HERE / "banner.bmp")


def make_dialog() -> None:
    """493 x 312 backdrop of the welcome / finish dialogs.

    The whole image sits behind the dialog text, so the area to the right of
    the artwork must stay light - the installer draws black text on it.
    """
    width, height = 493, 312
    panel_w = 172
    img = Image.new("RGB", (width, height), (251, 252, 254))
    img.paste(gradient(panel_w, height), (0, 0))
    draw = ImageDraw.Draw(img)

    bars(draw, 36, 108, 2.3)

    name = font(15, bold=True)
    draw.text((36, 152), "M Faraz Ali", font=name, fill=TEXT)

    small = font(9)
    draw.text((37, 174), f"System Widget {widget_version()}", font=small, fill=DIM)

    draw.line([(36, 200), (146, 200)], fill=(40, 46, 60), width=1)

    tiny = font(8)
    draw.text((37, 210), "CPU   RAM   GPU", font=tiny, fill=(92, 102, 120))
    draw.text((37, 224), "NET   POWER", font=tiny, fill=(92, 102, 120))

    img.save(HERE / "dialog.bmp")


if __name__ == "__main__":
    make_banner()
    make_dialog()
    print("wrote installer/banner.bmp and installer/dialog.bmp")
