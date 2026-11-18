# -*- coding: utf-8 -*-
"""表情下载：域名白名单、扩展名探测、缓存与失败降级"""
import io
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core import stickers  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PNG = b'\x89PNG\r\n\x1a\n' + b'\0' * 64
GIF = b'GIF89a' + b'\0' * 64
OK_URL = 'http://wxapp.tc.qq.com/275/stodownload?m=' + 'a' * 32


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_safe_url():
    assert stickers.safe_cdn_url(OK_URL) == OK_URL
    assert stickers.safe_cdn_url('https://vweixinf.tc.qq.com/a')
    assert stickers.safe_cdn_url('http://evil.com/x') == ''
    assert stickers.safe_cdn_url('javascript:alert(1)') == ''
    assert stickers.safe_cdn_url('http://user:pass@wxapp.tc.qq.com/x') == ''
    assert stickers.safe_cdn_url('http://wxapp.tc.qq.com.evil.com/x') == ''
    print('  ok  表情域名白名单')


def test_detect_ext():
    assert stickers.detect_ext(PNG) == '.png'
    assert stickers.detect_ext(GIF) == '.gif'
    assert stickers.detect_ext(b'\xff\xd8\xff' + b'\0' * 10) == '.jpg'
    assert stickers.detect_ext(b'hello') == ''
    print('  ok  扩展名探测')


def test_download_and_cache():
    with tempfile.TemporaryDirectory() as td:
        def fake_urlopen(req, timeout=0):
            return _Resp(PNG)

        with mock.patch.object(stickers.urllib.request, 'urlopen', fake_urlopen):
            path = stickers.download_one('a' * 32, OK_URL, td)
            assert path and path.endswith('.png') and os.path.exists(path), path
            # 第二次不再联网
            with mock.patch.object(stickers.urllib.request, 'urlopen',
                                   side_effect=AssertionError('should cache')):
                again = stickers.download_one('a' * 32, OK_URL, td)
            assert again == path, again
            # 非白名单地址直接失败
            assert stickers.download_one('b' * 32, 'http://evil.com/x', td) == ''
    print('  ok  下载与缓存')


def test_download_many_dedup():
    with tempfile.TemporaryDirectory() as td:
        calls = []

        def fake_urlopen(req, timeout=0):
            calls.append(req.full_url)
            return _Resp(GIF)

        with mock.patch.object(stickers.urllib.request, 'urlopen', fake_urlopen):
            res = stickers.download_many(
                [('a' * 32, OK_URL), ('a' * 32, OK_URL),
                 ('b' * 32, 'http://evil.com/x')], td)
        assert res['total'] == 1 and res['ok'] == 1, res
        assert len(calls) == 1, calls
    print('  ok  批量下载去重')


if __name__ == '__main__':
    test_safe_url()
    test_detect_ext()
    test_download_and_cache()
    test_download_many_dedup()
    print('STICKER TESTS OK')
