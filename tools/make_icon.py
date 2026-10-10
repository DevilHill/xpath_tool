"""生成应用图标 app.ico（圆角渐变底 + 白色定位准星）。

用法：python tools/make_icon.py
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

SIZE = 512
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "web", "app.ico")


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make() -> Image.Image:
    c1 = (99, 102, 241)   # #6366f1
    c2 = (139, 92, 246)   # #8b5cf6
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    grad = Image.new("RGBA", (SIZE, SIZE))
    gd = grad.load()
    for y in range(SIZE):
        for x in range(SIZE):
            t = (x + y) / (2 * SIZE)
            gd[x, y] = lerp(c1, c2, t) + (255,)

    # 圆角遮罩
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=int(SIZE * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    cx = cy = SIZE / 2
    r = SIZE * 0.26
    w = int(SIZE * 0.055)
    white = (255, 255, 255, 255)

    # 准星圆环
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=white, width=w)
    # 四向刻度
    tick = SIZE * 0.11
    d.line([cx, cy - r - tick, cx, cy - r + w * 0.5], fill=white, width=w)
    d.line([cx, cy + r + tick, cx, cy + r - w * 0.5], fill=white, width=w)
    d.line([cx - r - tick, cy, cx - r + w * 0.5, cy], fill=white, width=w)
    d.line([cx + r + tick, cy, cx + r - w * 0.5, cy], fill=white, width=w)
    # 中心点
    dr = SIZE * 0.045
    d.ellipse([cx - dr, cy - dr, cx + dr, cy + dr], fill=white)
    return img


def main() -> None:
    img = make()
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(OUT, format="ICO", sizes=sizes)
    png = OUT.replace(".ico", ".png")
    img.resize((256, 256), Image.LANCZOS).save(png)
    print("图标已生成：", OUT)
    print("预览图：", png)

    # 浏览器扩展图标
    ext_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension", "icons")
    os.makedirs(ext_dir, exist_ok=True)
    for size in (16, 32, 48, 128):
        img.resize((size, size), Image.LANCZOS).save(os.path.join(ext_dir, f"icon{size}.png"))
    print("扩展图标已生成：", ext_dir)


if __name__ == "__main__":
    main()
