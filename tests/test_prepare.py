# -*- coding: utf-8 -*-
"""按会话准备数据的离线测试（临时文件 + 合成消息）。"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core import media  # noqa: E402
from app.core.export import collect_media_ids  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def _touch(path, data=b'x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


def test_plan_images_filter():
    with tempfile.TemporaryDirectory() as td:
        attach = os.path.join(td, 'attach')
        img = os.path.join(attach, 'abc', '2026-01', 'Img')
        for name in ('111.dat', '111_h.dat', '222.dat'):
            _touch(os.path.join(img, name))
        pending, skipped = media._plan_images(
            attach, os.path.join(td, 'out'), only_md5s={'111'})
        names = sorted(os.path.basename(p[0]) for p in pending)
        assert names == ['111.dat', '111_h.dat'], names
        assert skipped == 0
    print('OK: 图片只匹配所选 md5（含缩略图）')


def test_plan_wxam_filter():
    with tempfile.TemporaryDirectory() as td:
        for name in ('111.hevc', '222.hevc'):
            _touch(os.path.join(td, name))
        pending, _ = media._plan_wxam(td, only_md5s={'111'})
        assert [os.path.basename(p[0]) for p in pending] == ['111.hevc']
    print('OK: WxAM 只匹配所选 md5')


def test_plan_voices_filter():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, 'media_0.db')
        c = sqlite3.connect(db)
        c.execute('create table Name2Id (user_name text)')
        c.execute('create table VoiceInfo (chat_name_id int, create_time int, '
                  'local_id int, voice_data blob)')
        c.execute("insert into Name2Id (rowid, user_name) values (1, 'chatA')")
        c.execute("insert into Name2Id (rowid, user_name) values (2, 'chatB')")
        c.execute("insert into VoiceInfo values (1, 1700000000, 1, x'00')")
        c.execute("insert into VoiceInfo values (1, 1700000001, 2, x'00')")
        c.execute("insert into VoiceInfo values (2, 1700000002, 3, x'00')")
        c.commit()
        c.close()
        pending, _ = media._plan_voices(
            db, os.path.join(td, 'voices'), only_messages={('chatA', 1)})
        assert len(pending) == 1 and pending[0][0].endswith('_1.wav'), pending
    print('OK: 语音只匹配所选 (会话, local_id)')


class FakeStore:
    def __init__(self, msgs):
        self._msgs = msgs

    def messages(self, username):
        return self._msgs


def test_collect_media_ids():
    md5_img = 'a' * 32
    md5_thumb = 'c' * 32
    md5_vid = 'b' * 32
    msgs = [
        {'local_id': 1, 'type': 'image', 'kind': 'image', 'image_md5': md5_img},
        {'local_id': 2, 'type': 'voice', 'kind': 'voice'},
        {'local_id': 3, 'type': 'video', 'kind': 'video', 'video_md5': md5_vid},
        {'local_id': 4, 'type': 'app', 'kind': 'chat_history', 'content': {
            'records': [
                {'kind': 'image', 'md5': md5_img, 'thumb_md5': md5_thumb},
                {'kind': 'video', 'video_md5': md5_vid},
            ]}},
    ]
    ids = collect_media_ids(FakeStore(msgs), ['chatA'])
    assert ids['images'] == {md5_img, md5_thumb}, ids['images']
    assert ids['videos'] == {md5_vid}, ids['videos']
    assert ids['voices'] == {('chatA', 2)}, ids['voices']
    print('OK: 所选会话媒体标识收集正确')


def main():
    test_plan_images_filter()
    test_plan_wxam_filter()
    test_plan_voices_filter()
    test_collect_media_ids()
    print('PREPARE TESTS OK')


if __name__ == '__main__':
    main()
