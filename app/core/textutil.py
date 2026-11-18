# -*- coding: utf-8 -*-
"""文本与链接清洗

微信消息里的引用/转发内容可能被多次 HTML 转义，出现 `&amp;amp;`、
`&lt;/url&gt;` 等残留；直接当链接打开会得到平台的 404（例如 B 站返回
`{"code":-404,"message":"啥都木有"}`）。这里统一做多轮反转义并截断 XML 尾巴。
"""
import html
import re

# URL 中不应出现的字符：空白、尖括号、引号；遇到即截断
_URL_STOP = re.compile(r'[\s<>"\']')


def deep_unescape(text, rounds: int = 3):
    """重复反转义，直到不再变化（最多 rounds 次）"""
    if not text:
        return text
    text = str(text)
    for _ in range(max(1, rounds)):
        new = html.unescape(text)
        if new == text:
            break
        text = new
    return text


def clean_url(url):
    """清洗 URL：多轮反转义，并截掉 `</url>`、空白等 XML 残留"""
    if not url:
        return ''
    s = deep_unescape(str(url).strip())
    return _URL_STOP.split(s, 1)[0].strip()


def clean_text(text):
    """清洗展示文本中的多次转义（不截断正文）"""
    return deep_unescape(text)
