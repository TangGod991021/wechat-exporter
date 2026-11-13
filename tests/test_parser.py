# -*- coding: utf-8 -*-
"""富消息解析测试（使用合成 XML，不依赖真实聊天数据）

如需对真实数据库做抽样验证，设置环境变量：
    set WECHAT_EXPORTER_DB=D:\\path\\to\\message_0.db
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.message_parser import parse_content, split_local_type  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

QUOTE_XML = """<?xml version="1.0"?>
<msg><appmsg appid="" sdkver="0">
<title>https://example.com/product?id=123&amp;from=demo @张三 这个已上架</title>
<des /><action /><type>57</type>
<refermsg>
<content>123 老师，辛苦这条链接上架一下哦</content>
<displayname>李四</displayname>
<type>1</type>
</refermsg>
</appmsg><fromusername>wxid_demo</fromusername></msg>"""

LINK_XML = """<msg><appmsg><title>邀请你加入群聊</title>
<des>“A”邀请你加入群聊“演示群”，进入可查看详情。</des>
<type>5</type><url><![CDATA[https://example.com/invite?ticket=abc]]></url>
</appmsg></msg>"""

FILE_XML = """<msg><appmsg><title>工作交接.zip</title><type>6</type>
<appattach><totallen>5767168</totallen></appattach></appmsg></msg>"""

CHAT_HISTORY_XML = """<msg><appmsg><title>张三与李四的聊天记录</title>
<des>张三: 你好</des><type>19</type>
<recorditem><![CDATA[<recordinfo><title>张三与李四的聊天记录</title>
<datalist count="2">
<dataitem datatype="1"><sourcename>张三</sourcename>
<sourcetime>2026-01-01 10:00</sourcetime><datadesc>你好</datadesc></dataitem>
<dataitem datatype="2"><sourcename>李四</sourcename>
<sourcetime>2026-01-01 10:01</sourcetime><datadesc>[图片]</datadesc>
<fullmd5>0123456789abcdef0123456789abcdef</fullmd5></dataitem>
</datalist></recordinfo>]]></recorditem></appmsg></msg>"""

PAT_XML = """<msg><appmsg><title>“王五” 拍了拍我</title><type>62</type></appmsg></msg>"""


def test_split_type():
    assert split_local_type(244813135921) == (49, 57)
    assert split_local_type(1) == (1, 0)


def test_quote():
    p = parse_content((57 << 32) | 49, QUOTE_XML)
    assert p['kind'] == 'quote'
    assert p['quote']['sender'] == '李四'
    assert '链接上架' in p['quote']['text']
    assert '这个已上架' in p['reply']
    assert '<appmsg' not in p['text']


def test_link():
    p = parse_content((5 << 32) | 49, LINK_XML)
    assert p['kind'] == 'link'
    assert p['url'] == 'https://example.com/invite?ticket=abc'
    assert '邀请你加入群聊' in p['text']


def test_file():
    p = parse_content((6 << 32) | 49, FILE_XML)
    assert p['kind'] == 'file'
    assert p['title'] == '工作交接.zip'
    assert p['size'] == '5.5 MB'


def test_chat_history():
    p = parse_content((19 << 32) | 49, CHAT_HISTORY_XML)
    assert p['kind'] == 'chat_history'
    assert len(p['records']) == 2
    assert p['records'][0]['sender'] == '张三'
    assert p['records'][0]['text'] == '你好'
    assert p['records'][1]['md5'] == '0123456789abcdef0123456789abcdef'


def test_pat():
    p = parse_content((62 << 32) | 49, PAT_XML)
    assert p['kind'] == 'pat'
    assert '拍了拍我' in p['text']


def test_unknown_never_leaks_xml():
    p = parse_content((999 << 32) | 49, '<msg><appmsg><type>999</type></appmsg></msg>')
    assert '<msg>' not in p['text'] and '<appmsg' not in p['text']


def test_real_db_optional():
    db = os.environ.get('WECHAT_EXPORTER_DB', '')
    if not db or not os.path.exists(db):
        print('跳过真实数据库抽样（未设置 WECHAT_EXPORTER_DB）')
        return
    import sqlite3
    import zstandard as zstd
    d = zstd.ZstdDecompressor()

    def dec(v):
        if isinstance(v, bytes) and v[:4] == b'\x28\xb5\x2f\xfd':
            try:
                return d.decompress(v).decode('utf-8', 'replace')
            except Exception:
                return ''
        return v.decode('utf-8', 'replace') if isinstance(v, bytes) else (v or '')

    c = sqlite3.connect(db)
    tabs = [r[0] for r in c.execute(
        "select name from sqlite_master where type='table' and name like 'Msg_%'")]
    tabs = [t for t in tabs if t.count('_') == 1]
    checked = 0
    for t in tabs:
        for lt, content in c.execute(
                f'select local_type, message_content from "{t}" '
                f'where local_type > 4294967296 limit 200'):
            p = parse_content(lt, dec(content))
            assert '<appmsg' not in p['text'] and '<msg>' not in p['text']
            checked += 1
        if checked > 2000:
            break
    c.close()
    print(f'真实数据库抽样 {checked} 条，未发现 XML 泄漏')


if __name__ == '__main__':
    test_split_type()
    test_quote()
    test_link()
    test_file()
    test_chat_history()
    test_pat()
    test_unknown_never_leaks_xml()
    test_real_db_optional()
    print('PARSER TESTS OK')
