# -*- coding: utf-8 -*-
"""本地媒体缺失时，聊天记录中要明确标注“已过期或已被清理”"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.export import (ChatStore, MISSING_IMAGE, MISSING_IMAGE_THUMB,
                             MISSING_VIDEO, MISSING_VOICE)

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TS = 1767225600


def _store(**overrides):
    s = object.__new__(ChatStore)
    s.my_wxid = ''
    s.sticker_dir = ''
    s.file_dir = ''
    s.attach_dir = ''
    s.hardlink_db = ''
    s.data_dir = ''
    s.voices_dir = ''
    s.images_dir = ''
    s.video_roots = []
    s.video_cache = ''
    s.video_playback_dir = ''
    s.ffmpeg = 'ffmpeg'
    s._file_index = None
    s._image_index = None
    s._image_suffix = None
    s._hardlink_names = None
    s._find_image_info = lambda md5: (None, '')
    s._find_image = lambda md5: None
    s._find_voice = lambda chat, lid: None
    s._find_video = lambda md5: None
    s.hardlink_stem = lambda md5, kind='image': ''
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _image_msg(store, content=None):
    content = content or '<msg><img md5="%s" /></msg>' % ('a' * 32)
    return store._parse('chat', {}, {}, (1, 3, 0, TS, content, None))


def test_image_expired():
    m = _image_msg(_store())
    assert m['kind'] == 'image', m
    assert m['media'] == '', m
    assert MISSING_IMAGE in m['text'], m['text']
    print('  ok  图片缺失提示')


def test_image_thumbnail_only():
    store = _store(_find_image_info=lambda md5: ('C:/x_t.jpg', '_t'))
    m = _image_msg(store)
    assert m['media'].endswith('_t.jpg'), m
    assert MISSING_IMAGE_THUMB in m['text'], m['text']
    print('  ok  仅缩略图提示')


def test_voice_and_video_expired():
    voice = ('<msg><voicemsg voicelength="3000" /></msg>')
    m = _store()._parse('chat', {}, {}, (1, 34, 0, TS, voice, None))
    assert MISSING_VOICE in m['text'], m['text']

    video = ('<msg><videomsg md5="%s" length="2048" /></msg>' % ('b' * 32))
    m = _store()._parse('chat', {}, {}, (1, 43, 0, TS, video, None))
    assert MISSING_VIDEO in m['text'], m['text']
    print('  ok  语音/视频缺失提示')


CHAT_HISTORY = ('<msg><appmsg><title>聊天记录</title><type>19</type>'
                '<recorditem><![CDATA[<recordinfo><datalist count="2">'
                '<dataitem datatype="2"><datadesc>[图片]</datadesc>'
                '<fullmd5>cccccccccccccccccccccccccccccccc</fullmd5></dataitem>'
                '<dataitem datatype="4"><datadesc>[视频]</datadesc>'
                '<fullmd5>dddddddddddddddddddddddddddddddd</fullmd5></dataitem>'
                '</datalist></recordinfo>]]></recorditem></appmsg></msg>')


def test_record_media_expired():
    m = _store()._parse('chat', {}, {}, ((19 << 32) | 49, 49, 0, TS,
                                        CHAT_HISTORY, None))
    recs = m['content']['records']
    assert MISSING_IMAGE in recs[0]['text'], recs[0]['text']
    assert MISSING_VIDEO in recs[1]['text'], recs[1]['text']
    print('  ok  转发记录缺失提示')


if __name__ == '__main__':
    test_image_expired()
    test_image_thumbnail_only()
    test_voice_and_video_expired()
    test_record_media_expired()
    print('MISSING MEDIA TESTS OK')
