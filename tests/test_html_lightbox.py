# -*- coding: utf-8 -*-
"""导出 HTML 的图片放大预览（离线字符串检查）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.export import write_html  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def main():
    msgs = [
        {'sender': '陈一', 'time': '2026-01-01 10:00', 'kind': 'text',
         'text': '看这个图', 'media': 'pic.png', 'ts': 1},
        {'sender': '我', 'time': '2026-01-01 10:01', 'kind': 'chat_history',
         'text': '聊天记录', 'media': '', 'ts': 2,
         'content': {'title': '转发记录', 'records': [
             {'sender': '陈一', 'time': '10:02', 'text': '图片',
              'kind': 'image', 'media': 'pic2.png'}]}},
    ]
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, 'index.html')
        write_html(out, '测试会话', msgs, uri_fn=lambda p: p)
        text = open(out, encoding='utf-8').read()

    assert 'id="lightbox"' in text
    assert 'class="chat-img"' in text and 'title="点击放大"' in text
    assert 'class="ri-img"' in text and 'title="点击放大"' in text
    assert "classList.contains('chat-img')" in text
    assert "e.key==='Escape'" in text
    assert 'max-height:92vh' in text
    print('HTML LIGHTBOX TESTS OK')


if __name__ == '__main__':
    main()
