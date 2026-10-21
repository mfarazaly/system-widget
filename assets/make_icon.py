"""Generates assets/icon.ico (run with: py assets/make_icon.py)."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
BG = (12, 14, 19, 255)
BORDER = (43, 50, 66, 255)
BARS = (
    (0.62, (76, 154, 255, 255)),
    (0.95, (176, 124, 255, 255)),
    (0.42, (45, 212, 167, 255)),
)


def render() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = 26
    draw.rounded_rectangle(
        [margin, margin, SIZE - margin, SIZE - margin],
        radius=205,
        fill=BG,
        outline=BORDER,
        width=15,
    )

    bar_h = 150
    gap = 88
    total = len(BARS) * bar_h + (len(BARS) - 1) * gap
    x0 = 150
    width = SIZE - 2 * x0
    y = (SIZE - total) // 2

    for fraction, colour in BARS:
        draw.rounded_rectangle(
            [x0, y, x0 + int(width * fraction), y + bar_h],
            radius=bar_h // 2,
            fill=colour,
        )
        y += bar_h + gap

    return img


def main() -> None:
    out = Path(__file__).with_name("icon.ico")
    icon = render()
    icon.resize((256, 256), Image.LANCZOS).save(out.with_name("icon.png"))
    icon.save(
        out,
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)],
    )
    print("wrote", out)


if __name__ == "__main__":
    main()
