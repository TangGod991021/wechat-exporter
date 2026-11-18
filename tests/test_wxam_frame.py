# -*- coding: utf-8 -*-
"""WXAM/HEVC 多帧图片：首帧白图识别与内容帧选择"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw  # noqa: E402

from app.core import media  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


class FakeFrame:
    def __init__(self, img):
        self.img = img

    def to_image(self):
        return self.img.copy()


def _white(w=120, h=60):
    return Image.new('RGB', (w, h), 'white')


def _content(w=120, h=60):
    img = Image.new('RGB', (w, h), 'white')
    d = ImageDraw.Draw(img)
    for i in range(10):
        d.line([(0, i * 6), (w, i * 6 + 3)], fill='black', width=2)
    return img


def test_pick_content_frame():
    frames = [FakeFrame(_white()), FakeFrame(_content())]
    best = media._pick_content_frame(iter(frames))
    assert best is not None
    assert media._image_is_blank(best) is False
    print('  ok  跳过首帧白图，选择内容帧')


def test_blank_detection():
    with tempfile.TemporaryDirectory() as td:
        white = os.path.join(td, 'white.jpg')
        _white().save(white, 'JPEG')
        content = os.path.join(td, 'content.jpg')
        _content().save(content, 'JPEG')
        assert media._is_blank_image(white) is True
        assert media._is_blank_image(content) is False
        assert media._is_blank_image(os.path.join(td, 'missing.jpg')) is False
    print('  ok  空白图检测')


def test_plan_reconverts_blank_output():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'x.hevc')
        open(src, 'wb').write(b'hevc')
        dst = os.path.join(td, 'x.jpg')
        _white().save(dst, 'JPEG')
        os.utime(dst, (os.path.getmtime(src) + 10,) * 2)
        pending, skipped = media._plan_wxam(td)
        assert pending == [(src, dst)] and skipped == 0, (pending, skipped)

        img = _content()
        img.save(dst, 'JPEG')
        pending, skipped = media._plan_wxam(td)
        assert pending == [] and skipped == 1, (pending, skipped)
    print('  ok  旧空白图会重新转换')


if __name__ == '__main__':
    test_pick_content_frame()
    test_blank_detection()
    test_plan_reconverts_blank_output()
    print('WXAM FRAME TESTS OK')
