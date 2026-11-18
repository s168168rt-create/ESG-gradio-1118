"""產生 PWA 圖示(需要 Pillow、numpy):python tools/make_icons.py"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "static" / "icons"
OUT.mkdir(parents=True, exist_ok=True)
C1, C2 = np.array([15, 118, 110]), np.array([37, 99, 235])   # teal → blue


def make(size: int, rounded: bool, content: float) -> Image.Image:
    s = size * 4                                            # 4 倍超取樣,縮小後邊緣較平滑
    y, x = np.mgrid[0:s, 0:s]
    t = ((x + y) / (2 * s))[..., None]
    img = Image.fromarray((C1 * (1 - t) + C2 * t).astype("uint8"), "RGB").convert("RGBA")

    if rounded:
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=255)
        img.putalpha(mask)

    d = ImageDraw.Draw(img)
    area = s * content                                      # 內容區(maskable 需留安全邊界)
    left = (s - area) / 2
    bottom = (s + area) / 2 - area * 0.06
    bar_w, gap = area * 0.2, area * 0.1
    x0 = left + (area - (3 * bar_w + 2 * gap)) / 2
    for i, h in enumerate((0.38, 0.62, 0.9)):
        bx = x0 + i * (bar_w + gap)
        d.rounded_rectangle((bx, bottom - area * h * 0.88, bx + bar_w, bottom),
                            radius=bar_w * 0.28, fill=(255, 255, 255, 255 if i == 2 else 225))
    d.rounded_rectangle((left, bottom + area * 0.03, left + area, bottom + area * 0.06),
                        radius=area * 0.015, fill=(255, 255, 255, 140))
    return img.resize((size, size), Image.LANCZOS)


make(192, True, 0.62).save(OUT / "icon-192.png")
make(512, True, 0.62).save(OUT / "icon-512.png")
make(512, False, 0.5).save(OUT / "icon-maskable-512.png")   # maskable:滿版背景 + 安全區
make(180, False, 0.6).save(OUT / "apple-touch-icon.png")     # iOS 自行裁圓角
print("icons ->", OUT)
