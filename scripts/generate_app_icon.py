#!/usr/bin/env python3
"""
生成 PDF Studio 应用图标 app.ico / app.png
用法：python scripts/generate_app_icon.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "app" / "resources" / "icons"
ICO_PATH = ICON_DIR / "app.ico"
PNG_PATH = ICON_DIR / "app.png"

BRAND = (0, 120, 212)
FOLD = (0, 90, 180)
PAGE = (255, 255, 255)


def _draw_icon(size: int):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = max(1, size // 10)
    body = [m, m, size - m, size - m]
    radius = max(2, size // 8)
    draw.rounded_rectangle(body, radius=radius, fill=BRAND + (255,))

    fold = size // 4
    tri = [
        (size - m - fold, m),
        (size - m, m),
        (size - m, m + fold),
    ]
    draw.polygon(tri, fill=FOLD + (255,))

    inner = [
        m + size // 12,
        m + size // 8,
        size - m - size // 6,
        size - m - size // 10,
    ]
    draw.rounded_rectangle(inner, radius=max(1, size // 16), fill=PAGE + (240,))

    bar_h = max(1, size // 18)
    gap = max(2, size // 14)
    x0 = inner[0] + gap
    x1 = inner[2] - gap
    y = inner[1] + gap * 2
    for _ in range(3):
        draw.rectangle([x0, y, x1, y + bar_h], fill=BRAND + (200,))
        y += bar_h + gap

    if size >= 48:
        label = "PDF"
        font_size = max(8, size // 5)
        try:
            from PIL import ImageFont

            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        tw, th = draw.textbbox((0, 0), label, font=font)[2:]
        tx = (size - tw) // 2
        ty = inner[3] - th - gap
        draw.text((tx, ty), label, fill=BRAND + (255,), font=font)

    return img


def main() -> int:
    try:
        from PIL import Image
    except ImportError as e:
        raise SystemExit("需要 Pillow：pip install Pillow") from e

    ICON_DIR.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [_draw_icon(s) for s in sizes]
    images[-1].save(
        ICO_PATH,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1],
    )
    images[-1].save(PNG_PATH, format="PNG")
    print(f"已生成: {ICO_PATH}")
    print(f"已生成: {PNG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
