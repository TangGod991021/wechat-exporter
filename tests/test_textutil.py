# -*- coding: utf-8 -*-
"""多轮转义与畸形 URL 清洗

微信引用/转发里可能出现 `&amp;amp;`、`&lt;/url&gt;` 等残留，
直接打开会让 B 站返回 {"code":-404,"message":"啥都木有"}。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.textutil import clean_text, clean_url, deep_unescape  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BAD = ('https://b23.tv/XhacprH?share_medium=android&amp;amp;'
       'share_source=weixin&amp;amp;bbid=ABC&amp;amp;ts=1760319987557'
       '&lt;/url&gt;')
GOOD = ('https://b23.tv/XhacprH?share_medium=android&'
        'share_source=weixin&bbid=ABC&ts=1760319987557')


def test_deep_unescape():
    assert deep_unescape(BAD) == GOOD + '</url>'
    assert deep_unescape('&amp;lt;') == '<'
    assert deep_unescape('普通文本') == '普通文本'
    print('  ok  多轮反转义')


def test_clean_url():
    assert clean_url(BAD) == GOOD
    assert clean_url('  ' + GOOD + '  ') == GOOD
    assert clean_url('https://a.com/x">evil') == 'https://a.com/x'
    assert clean_url('') == ''
    print('  ok  URL 清洗')


def test_clean_text_keeps_body():
    assert clean_text('你好&amp;再见') == '你好&再见'
    print('  ok  正文清洗')


def test_safe_href_and_linkify():
    from app.core.export import _safe_href, linkify
    assert _safe_href(BAD) == GOOD
    html = linkify('看 ' + BAD)
    assert '&amp;amp;' not in html and '&lt;/url&gt;' not in html, html
    assert f'href="{GOOD.replace("&", "&amp;")}"' in html, html
    print('  ok  导出链接清洗')


def test_parser_text_url():
    from app.core.message_parser import parse_content
    p = parse_content(1, '看这个 ' + BAD)
    assert '&amp;amp;' not in p['text'], p['text']
    print('  ok  正文多轮反转义')


if __name__ == '__main__':
    test_deep_unescape()
    test_clean_url()
    test_clean_text_keeps_body()
    test_safe_href_and_linkify()
    test_parser_text_url()
    print('TEXT UTIL TESTS OK')
