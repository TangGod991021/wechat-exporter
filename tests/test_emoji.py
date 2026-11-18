# -*- coding: utf-8 -*-
"""内置表情代码 -> Unicode 转换"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.emoji import convert, contains_code  # noqa: E402
from app.core.message_parser import parse_content  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def test_convert_basic():
    assert convert('好的[微笑]') == '好的😊'
    assert convert('[破涕为笑][抱拳]') == '😂🙏'
    assert convert('[NO]和[OK]') == '🙅和👌'
    assert convert('[未知代码]') == '[未知代码]'
    assert convert('') == ''
    assert contains_code('[红包]') and not contains_code('普通文本')
    print('  ok  基础转换')


def test_parse_text_and_quote():
    p = parse_content(1, '收到[抱拳]')
    assert p['text'] == '收到🙏', p

    quote = ('<msg><appmsg><title>好的[微笑]</title><type>57</type>'
             '<refermsg><content>收到[破涕为笑]</content>'
             '<displayname>张三[得意]</displayname><type>1</type>'
             '</refermsg></appmsg></msg>')
    p = parse_content((57 << 32) | 49, quote)
    assert '😊' in p['reply'] and '😂' in p['quote']['text'], p
    assert p['quote']['sender'] == '张三😎', p
    print('  ok  正文与引用转换')


def test_file_name_not_converted():
    xml = ('<msg><appmsg><title>报表[微笑].xlsx</title><type>6</type>'
           '<appattach><totallen>100</totallen><fileext>xlsx</fileext>'
           '</appattach></appmsg></msg>')
    p = parse_content((6 << 32) | 49, xml)
    assert p['title'] == '报表[微笑].xlsx', p
    assert '[微笑]' in p['text'], p
    print('  ok  文件名不转换')


def test_record_and_transfer():
    rec = ('<msg><appmsg><title>聊天记录</title><type>19</type>'
           '<recorditem><![CDATA[<recordinfo><datalist count="1">'
           '<dataitem datatype="1"><sourcename>李四</sourcename>'
           '<datadesc>太好了[鼓掌]</datadesc></dataitem>'
           '</datalist></recordinfo>]]></recorditem></appmsg></msg>')
    p = parse_content((19 << 32) | 49, rec)
    assert p['records'][0]['text'] == '太好了👏', p

    trans = ('<msg><appmsg><type>2000</type><wcpayinfo>'
             '<feedesc>￥1.00</feedesc><paymememo>谢谢[玫瑰]</paymememo>'
             '<receivertitle>已收款[OK]</receivertitle></wcpayinfo></appmsg></msg>')
    p = parse_content((2000 << 32) | 49, trans)
    assert p['memo'] == '谢谢🌹' and p['status'] == '已收款👌', p
    print('  ok  转发记录与转账转换')


if __name__ == '__main__':
    test_convert_basic()
    test_parse_text_and_quote()
    test_file_name_not_converted()
    test_record_and_transfer()
    print('EMOJI TESTS OK')
