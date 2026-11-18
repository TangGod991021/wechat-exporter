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


STICKER_XML = ('<msg><appmsg><type>8</type><appattach>'
               '<totallen>12345</totallen><emoticonmd5>aa</emoticonmd5>'
               '<fileext>gif</fileext></appattach></appmsg></msg>')

NOTE_XML = ('<msg><appmsg><title></title><des>房源信息\\n[视频]\\n[图片]</des>'
            '<type>24</type><recorditem>'
            '&lt;recordinfo&gt;&lt;datalist count="1"&gt;'
            '&lt;dataitem datatype="2"&gt;'
            '&lt;sourcename&gt;张三&lt;/sourcename&gt;'
            '&lt;fullmd5&gt;0123456789abcdef0123456789abcdef&lt;/fullmd5&gt;'
            '&lt;/dataitem&gt;&lt;/datalist&gt;&lt;/recordinfo&gt;'
            '</recorditem></appmsg></msg>')

ANNOUNCEMENT_XML = ('<msg><appmsg><type>87</type><announcement><![CDATA['
                    '<group_notice_item><datalist count="1">'
                    '<dataitem datatype="8"><datatitle>群公告内容.htm</datatitle>'
                    '<datadesc>60B</datadesc></dataitem>'
                    '</datalist></group_notice_item>]]></announcement></appmsg></msg>')

CARD_XML = ('<msg bigheadimgurl="" smallheadimgurl="" username="wxid_card" '
            'nickname="张三" alias="" />')

LOCATION_XML = ('<msg><location x="26.616711" y="106.649033" scale="15" '
                'label="贵州省贵阳市某大厦1楼" poiname="某菜馆" '
                'cityname="贵阳市" /></msg>')


def test_appmsg_new_types():
    p = parse_content((8 << 32) | 49, STICKER_XML)
    assert p['kind'] == 'sticker' and p['text'] == '[动图]', p

    p = parse_content((24 << 32) | 49, NOTE_XML)
    assert p['kind'] == 'chat_history' and p['is_note'] is True, p
    assert len(p['records']) == 1 and p['records'][0]['kind'] == 'image', p
    assert p['text'].startswith('[笔记]'), p

    p = parse_content((87 << 32) | 49, ANNOUNCEMENT_XML)
    assert p['kind'] == 'announcement', p
    assert '群公告内容' in p['des'], p
    assert p['text'].startswith('[群公告]'), p


EMOJI_47_XML = ('<msg><emoji fromusername = "wxid_a" tousername = "wxid_b" '
                'type="2" md5="0123456789abcdef0123456789abcdef" len = "1234" '
                'cdnurl = "http://wxapp.tc.qq.com/x?m=0123456789abcdef0123456789abcdef&amp;f=1" '
                '/></msg>')

import base64  # noqa: E402

_EMOJI_URL = (b'http://vweixinf.tc.qq.com/110/20401/stodownload?'
              b'm=abcdefabcdefabcdefabcdefabcdefab&filekey=x')
_EMOJI_INFO = base64.b64encode(
    b'\n abcdefabcdefabcdefabcdefabcdefab\x12\x01x' + _EMOJI_URL).decode()
EMOJI_8_XML = ('<msg><appmsg><type>8</type><appattach>'
               '<totallen>100</totallen>'
               '<emoticonmd5>abcdefabcdefabcdefabcdefabcdefab</emoticonmd5>'
               '<fileext>gif</fileext></appattach>'
               f'<emojiinfo>{_EMOJI_INFO}</emojiinfo></appmsg></msg>')

TRANSFER_XML = ('<msg><appmsg><title>微信转账</title><type>2000</type>'
                '<wcpayinfo><feedesc>￥88.00</feedesc>'
                '<paymememo>午饭</paymememo>'
                '<sendertitle>转账给你</sendertitle>'
                '<receivertitle>已收款</receivertitle>'
                '<transferid>tid_1</transferid><paymsgid>mid_1</paymsgid>'
                '</wcpayinfo></appmsg></msg>')

REDPACKET_XML = ('<msg><appmsg><title>微信红包</title><type>2001</type>'
                 '<wcpayinfo><sendertitle>恭喜发财，大吉大利</sendertitle>'
                 '<receivertitle>已存入零钱</receivertitle>'
                 '<paymememo>新年快乐</paymememo></wcpayinfo></appmsg></msg>')

RECORD_LINK_XML = ('<msg><appmsg><title>聊天记录</title><type>19</type>'
                   '<recorditem><![CDATA[<recordinfo><datalist count="1">'
                   '<dataitem datatype="5"><datatitle>文章标题</datatitle>'
                   '<sourcename>张三</sourcename><sourcetime>2026-01-01</sourcetime>'
                   '<link>https://mp.weixin.qq.com/s/demo</link>'
                   '<datadesc>摘要内容</datadesc></dataitem>'
                   '</datalist></recordinfo>]]></recorditem></appmsg></msg>')


def test_sticker_parsing():
    p = parse_content(47, EMOJI_47_XML)
    assert p['kind'] == 'sticker', p
    assert p['md5'] == '0123456789abcdef0123456789abcdef', p
    assert p['cdnurl'].startswith('http://wxapp.tc.qq.com/'), p
    assert p['size_bytes'] == 1234, p

    p = parse_content((8 << 32) | 49, EMOJI_8_XML)
    assert p['kind'] == 'sticker', p
    assert p['md5'] == 'abcdefabcdefabcdefabcdefabcdefab', p
    assert p['ext'] == 'gif', p
    assert any('m=abcdef' in u for u in p['cdnurls']), p
    assert p['cdnurl'], p


def test_transfer_and_redpacket():
    p = parse_content((2000 << 32) | 49, TRANSFER_XML)
    assert p['kind'] == 'transfer', p
    assert p['amount'] == '￥88.00', p
    assert p['memo'] == '午饭', p
    assert p['status'] == '已收款', p
    assert p['transferid'] == 'tid_1' and p['paymsgid'] == 'mid_1', p
    assert '￥88.00' in p['text'] and '午饭' in p['text'], p

    p = parse_content((2001 << 32) | 49, REDPACKET_XML)
    assert p['kind'] == 'redpacket', p
    assert p['memo'] == '新年快乐', p
    assert p['status'] == '已存入零钱', p


def test_record_link():
    p = parse_content((19 << 32) | 49, RECORD_LINK_XML)
    rec = p['records'][0]
    assert rec['kind'] == 'link', rec
    assert rec['url'] == 'https://mp.weixin.qq.com/s/demo', rec
    assert rec['title'] == '文章标题', rec


def test_card_and_location():
    p = parse_content(42, CARD_XML)
    assert p['kind'] == 'card' and '张三' in p['text'], p
    assert p['username'] == 'wxid_card', p

    p = parse_content(48, LOCATION_XML)
    assert p['kind'] == 'location' and '某大厦' in p['text'], p
    assert p['lat'] == '26.616711' and p['lng'] == '106.649033', p
    assert p['url'].startswith('https://uri.amap.com/marker?position=106.649033,26.616711'), p


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
    test_appmsg_new_types()
    test_sticker_parsing()
    test_transfer_and_redpacket()
    test_record_link()
    test_card_and_location()
    test_real_db_optional()
    print('PARSER TESTS OK')
