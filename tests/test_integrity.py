# -*- coding: utf-8 -*-
"""数据完整性测试：语音路径、转发图片 hardlink 映射、解密原子写与消息分片"""
import os
import sqlite3
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.decrypt import (  # noqa: E402
    PAGE_SZ, chat_db_rels, decrypt_all, decrypt_database,
)
from app.core.export import ChatStore  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

RECORD_XML = """<msg><appmsg><title>聊天记录</title><type>19</type>
<recorditem><![CDATA[<recordinfo><title>聊天记录</title>
<datalist count="1">
<dataitem datatype="2"><sourcename>张三</sourcename>
<sourcetime>2026-01-01 10:01</sourcetime>
<fullmd5>{md5}</fullmd5></dataitem>
</datalist></recordinfo>]]></recorditem></appmsg></msg>"""


def test_voice_uses_username_dir():
    with tempfile.TemporaryDirectory() as tmp:
        voices = os.path.join(tmp, 'voices')
        os.makedirs(os.path.join(voices, 'wxid_demo'))
        wav = os.path.join(voices, 'wxid_demo', '20260101_101010_7.wav')
        open(wav, 'wb').write(b'RIFF')
        store = ChatStore(os.path.join(tmp, 'data'), voices_dir=voices)
        row = (7, 34, 0, 1767225600,
               '<msg><voicelength>1500</voicelength></msg>', None)
        # 联系人备注与 wxid 不同，语音仍应按 wxid 目录找到
        m = store._parse('wxid_demo', {}, {'wxid_demo': '备注名'}, row)
        assert m['media'] == wav, m['media']
    print('  ok  语音按 username 目录定位')


def test_record_image_hardlink():
    msg_md5 = 'a' * 32
    local = 'localname123'
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, 'data')
        os.makedirs(os.path.join(data, 'hardlink'))
        db = sqlite3.connect(os.path.join(data, 'hardlink', 'hardlink.db'))
        db.execute('create table image_hardlink_info_v4'
                   '(md5 TEXT, file_name TEXT, type INTEGER)')
        db.execute('insert into image_hardlink_info_v4 values (?,?,?)',
                   (msg_md5, local + '.dat', 2))
        db.commit()
        db.close()
        images = os.path.join(tmp, 'images')
        os.makedirs(images)
        img = os.path.join(images, local + '.jpg')
        open(img, 'wb').write(b'\xff\xd8')

        store = ChatStore(data, images_dir=images)
        row = (1, (19 << 32) | 49, 0, 1767225600,
               RECORD_XML.format(md5=msg_md5), None)
        m = store._parse('wxid_demo', {}, {}, row)
        rec = m['content']['records'][0]
        assert rec['media'] == img, rec
        assert rec['image_md5'] == local, rec
    print('  ok  转发记录图片经 hardlink 映射')


def test_chat_db_rels_dynamic():
    with tempfile.TemporaryDirectory() as tmp:
        msg = os.path.join(tmp, 'message')
        os.makedirs(msg)
        for name in ('message_0.db', 'message_1.db', 'media_0.db', 'media_1.db',
                     'ignore.txt'):
            open(os.path.join(msg, name), 'wb').write(b'')
        rels = chat_db_rels(tmp)
        for rel in ('message/message_0.db', 'message/message_1.db',
                    'message/media_0.db', 'message/media_1.db'):
            assert rel in rels, rels
        assert 'message/ignore.txt' not in rels
    print('  ok  动态扫描 message_*.db 分片')


def test_decrypt_rejects_partial_source():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'a.db')
        dst = os.path.join(tmp, 'out', 'a.db')
        open(src, 'wb').write(b'x' * (PAGE_SZ + 10))
        assert decrypt_database(src, dst, b'0' * 32) is False
        assert not os.path.exists(dst), '不完整源库不应产生输出'
    print('  ok  拒绝不完整源库')


def test_decrypt_skips_only_matching_size():
    with tempfile.TemporaryDirectory() as tmp:
        rel = 'x.db'
        src = os.path.join(tmp, 'src', rel)
        dst = os.path.join(tmp, 'out', rel)
        os.makedirs(os.path.dirname(src))
        os.makedirs(os.path.dirname(dst))
        open(src, 'wb').write(b'x' * PAGE_SZ)
        open(dst, 'wb').write(b'x' * 10)  # 半截文件，大小不符
        os.utime(dst, (os.path.getmtime(src) + 10, os.path.getmtime(src) + 10))
        keys = {rel: {'enc_key': '00' * 32}}
        with mock.patch('app.core.decrypt.decrypt_database', return_value=True) as fn:
            res = decrypt_all(tmp + '/src', tmp + '/out', keys)
            assert fn.called, '大小不符应重新解密'
            assert res['failed'] == 0, res
        open(dst, 'wb').write(b'x' * PAGE_SZ)
        os.utime(dst, (os.path.getmtime(src) + 10, os.path.getmtime(src) + 10))
        with mock.patch('app.core.decrypt.decrypt_database', return_value=True) as fn:
            res = decrypt_all(tmp + '/src', tmp + '/out', keys)
            assert not fn.called, '大小一致且较新应跳过'
            assert res['skipped'] == 1, res
    print('  ok  跳过时校验输出大小')


def test_sender_prefix_stripped_for_xml():
    card = ('<msg bigheadimgurl="" username="wxid_card" nickname="张三" />')
    with tempfile.TemporaryDirectory() as tmp:
        store = ChatStore(os.path.join(tmp, 'data'))
        row = (1, 42, 1, 1767225600, 'wxid_demo:\n' + card, None)
        m = store._parse('wxid_demo', {1: 'wxid_demo'}, {'wxid_demo': '备注'}, row)
        assert m['kind'] == 'card', m
        assert '张三' in m['text'] and 'wxid_demo:' not in m['text'], m
    print('  ok  群聊发送者前缀（XML 类型）')


def main():
    test_voice_uses_username_dir()
    test_record_image_hardlink()
    test_sender_prefix_stripped_for_xml()
    test_chat_db_rels_dynamic()
    test_decrypt_rejects_partial_source()
    test_decrypt_skips_only_matching_size()
    print('数据完整性测试全部通过')


if __name__ == '__main__':
    main()
