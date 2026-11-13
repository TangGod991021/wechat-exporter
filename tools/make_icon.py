# -*- coding: utf-8 -*-
"""生成程序图标（原创图形：绿色圆角底 + 聊天气泡 + 导出箭头）。

输出：
    packaging/icon.ico          多尺寸 Windows 图标（16~256）
    packaging/icon.png          512px 预览图
    webui/public/favicon.ico    网页图标
    webui/public/favicon.png    网页图标（PNG 回退）

用法：python tools/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SIZE = 1024
GREEN_TOP = (48, 214, 132)
GREEN_BOTTOM = (4, 154, 76)
GREEN_MARK = (7, 178, 95)
WHITE = (255, 255, 255)


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def gradient_background(size: int) -> Image.Image:
    img = Image.new('RGB', (size, size))
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / (size - 1)
        color = tuple(
            int(GREEN_TOP[i] + (GREEN_BOTTOM[i] - GREEN_TOP[i]) * t) for i in range(3)
        )
        d.line([(0, y), (size, y)], fill=color)
    # 左上柔和高光，避免纯渐变过于扁平
    glow = Image.new('L', (size, size), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-size * 0.25, -size * 0.35, size * 0.75, size * 0.65), fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.10))
    white = Image.new('RGB', (size, size), (255, 255, 255))
    img = Image.composite(white, img, glow.point(lambda v: int(v * 0.45)))
    return img


def chat_bubble_mark(size: int) -> Image.Image:
    """白色聊天气泡 + 绿色向下箭头（导出含义）。"""
    layer = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    s = size / 1024

    def box(x1, y1, x2, y2):
        return (x1 * s, y1 * s, x2 * s, y2 * s)

    # 气泡尾巴（先画，和主体重叠融合）
    d.polygon(
        [(250 * s, 590 * s), (250 * s, 830 * s), (450 * s, 660 * s)],
        fill=WHITE,
    )
    # 气泡主体
    d.rounded_rectangle(box(180, 230, 844, 700), radius=int(150 * s), fill=WHITE)

    # 向下的导出箭头（绿色，嵌在气泡中）
    shaft = box(470, 318, 554, 520)
    d.rounded_rectangle(shaft, radius=int(20 * s), fill=GREEN_MARK)
    d.polygon(
        [(384 * s, 488 * s), (640 * s, 488 * s), (512 * s, 664 * s)],
        fill=GREEN_MARK,
    )
    return layer


def build_icon(size: int = SIZE) -> Image.Image:
    bg = gradient_background(size)
    corners = rounded_mask(size, int(size * 0.225))
    icon = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), corners)
    mark = chat_bubble_mark(size)
    icon.alpha_composite(mark)
    return icon


def main() -> None:
    icon = build_icon()
    packaging = ROOT / 'packaging'
    public = ROOT / 'webui' / 'public'
    public.mkdir(parents=True, exist_ok=True)

    icon.save(packaging / 'icon.png')
    icon.resize((512, 512), Image.Resampling.LANCZOS).save(packaging / 'icon-512.png')
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(
        packaging / 'icon.ico',
        format='ICO',
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(
        public / 'favicon.ico',
        format='ICO',
        sizes=[(16, 16), (32, 32), (48, 48)],
    )
    icon.resize((192, 192), Image.Resampling.LANCZOS).save(public / 'favicon.png')

    # 小尺寸预览，便于人工检查
    preview = Image.new('RGBA', (420, 140), (245, 246, 248, 255))
    x = 14
    for px in (16, 24, 32, 48, 64, 128):
        small = icon.resize((px, px), Image.Resampling.LANCZOS)
        preview.alpha_composite(small, (x, 70 - px // 2))
        x += px + 14
    build_dir = ROOT / 'build'
    build_dir.mkdir(exist_ok=True)
    preview.save(build_dir / 'icon-preview.png')

    print('生成完成：')
    for p in (packaging / 'icon.ico', packaging / 'icon.png',
              packaging / 'icon-512.png', public / 'favicon.ico',
              public / 'favicon.png'):
        print(f'  {p.relative_to(ROOT)}  {p.stat().st_size / 1024:.1f} KB')


if __name__ == '__main__':
    main()
