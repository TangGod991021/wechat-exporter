# -*- coding: utf-8 -*-
"""B 站短链检测、缓存与卡片状态"""
import json
import os
import sys
import tempfile
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core import links  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SHORT = 'https://b23.tv/woEQo7Z?share_medium=android&ts=1'
GOOD = 'https://b23.tv/SH4IpZA'


class _Resp:
    def __init__(self, status=200, headers=None, body=b''):
        self.status = status
        self.headers = headers or {}
        self._body = body

    def read(self, n=2048):
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Opener:
    def __init__(self, resp=None, error=None):
        self.resp = resp
        self.error = error

    def open(self, req, timeout=0):
        if self.error:
            raise self.error
        return self.resp


def test_basic():
    assert links.is_bilibili_short(SHORT)
    assert not links.is_bilibili_short('https://example.com/x')
    assert links.is_short_link(SHORT)
    s = links.search_url('视频 标题')
    assert s.startswith('https://search.bilibili.com/all?keyword=')
    assert '%20' in s and links.search_url('') == ''
    print('  ok  短链识别与搜索链接')


def test_resolve_redirect():
    resp = _Resp(302, {'Location':
                       'https://www.bilibili.com/video/BV1x?buvid=abc&x=1'})
    with mock.patch('app.core.links.urllib.request.build_opener',
                    return_value=_Opener(resp)):
        status, resolved = links.resolve(GOOD)
    assert status == 'valid', (status, resolved)
    assert resolved == 'https://www.bilibili.com/video/BV1x', resolved
    print('  ok  有效短链解析为直链')


def test_resolve_expired():
    body = b'{"code":-404,"message":"\\xe5\\x95\\xa5\\xe9\\x83\\xbd\\xe6\\x9c\\xa8\\xe6\\x9c\\x89","ttl":1}'
    with mock.patch('app.core.links.urllib.request.build_opener',
                    return_value=_Opener(_Resp(200, {}, body))):
        assert links.resolve(SHORT)[0] == 'expired'
    err = urllib.error.HTTPError(SHORT, 404, 'not found', {}, None)
    with mock.patch('app.core.links.urllib.request.build_opener',
                    return_value=_Opener(error=err)):
        assert links.resolve(SHORT)[0] == 'expired'
    print('  ok  失效短链识别')


def test_resolve_unknown():
    with mock.patch('app.core.links.urllib.request.build_opener',
                    return_value=_Opener(error=TimeoutError())):
        assert links.resolve(GOOD)[0] == 'unknown'
    print('  ok  网络失败不误判')


def test_cache_and_apply():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, 'link_status.json')
        with mock.patch('app.core.links.resolve',
                        return_value=('expired', '')) as res:
            cache = links.check_urls([SHORT, SHORT], path)
            assert res.call_count == 1, res.call_count
        assert cache[SHORT]['status'] == 'expired'
        assert json.load(open(path, encoding='utf-8'))[SHORT]['status'] == 'expired'
        # 缓存命中，不再联网
        with mock.patch('app.core.links.resolve',
                        side_effect=AssertionError('should cache')):
            links.check_urls([SHORT], path)
        content = {'kind': 'video_share', 'url': SHORT,
                   'search_url': links.search_url('标题')}
        links.apply_to_message(content, links.load_cache(path))
        assert content['link_expired'] is True, content
    print('  ok  缓存与状态回填')


def test_apply_valid_resolved():
    content = {'kind': 'video_share', 'url': GOOD}
    links.apply_to_message(content, {GOOD: {
        'status': 'valid', 'resolved': 'https://www.bilibili.com/video/BV1',
        'checked_at': 1}})
    assert content.get('resolved_url', '').endswith('/BV1'), content
    assert not content.get('link_expired')
    print('  ok  直链回填')


if __name__ == '__main__':
    test_basic()
    test_resolve_redirect()
    test_resolve_expired()
    test_resolve_unknown()
    test_cache_and_apply()
    test_apply_valid_resolved()
    print('LINK TESTS OK')
