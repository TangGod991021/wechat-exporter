# -*- coding: utf-8 -*-
"""导出容错测试：单会话失败不中断整批、平铺模式同名会话不覆盖"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.export import _safe_name, export_chats  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


class FakeStore:
    video_roots = []
    video_playback_dir = ''
    video_cache = ''
    ffmpeg = 'ffmpeg'

    def __init__(self, contacts, fail=()):
        self._contacts = contacts
        self._fail = set(fail)

    def contacts(self):
        return dict(self._contacts)

    def messages(self, username, since=None, until=None):
        if username in self._fail:
            raise RuntimeError('database is locked')
        return [{
            'local_id': 1, 'ts': 1767225600, 'time': '2026-01-01 00:00:00',
            'type': 'text', 'kind': 'text', 'sender': '我', 'text': '你好',
            'media': '', 'content': {},
        }]


def test_one_chat_failure_does_not_abort_batch():
    store = FakeStore({'u1': '张三', 'u2': '李四'}, fail=('u2',))
    with tempfile.TemporaryDirectory() as td:
        res = export_chats(store, ['u1', 'u2'], ['html', 'txt'],
                           None, None, td, archive=True)
        assert len(res['errors']) == 1, res
        assert res['errors'][0]['username'] == 'u2', res
        assert len(res['files']) == 2, res  # 成功的会话仍有 html + txt
        assert all(os.path.exists(p) for p in res['files']), res
        manifest = os.path.join(res['dir'], 'manifest.json')
        assert os.path.exists(manifest)
        data = json.load(open(manifest, encoding='utf-8'))
        assert data['errors'] and data['chats'], data
    print('  ok  单会话失败不中断整批')


def test_flat_mode_same_name_not_overwritten():
    store = FakeStore({'u1': '同名', 'u2': '同名'})
    with tempfile.TemporaryDirectory() as td:
        res = export_chats(store, ['u1', 'u2'], ['html'],
                           None, None, td, archive=False)
        assert len(res['files']) == 2, res
        assert len(set(res['files'])) == 2, res
        assert all(os.path.exists(p) for p in res['files']), res
    print('  ok  平铺模式同名会话不覆盖')


def test_missing_media_marked():
    class S(FakeStore):
        def __init__(self, media_path):
            super().__init__({'u1': '张三'})
            self.media_path = media_path

        def messages(self, username, since=None, until=None):
            m = super().messages(username)
            m[0]['media'] = self.media_path
            return m

    with tempfile.TemporaryDirectory() as td:
        missing = os.path.join(td, 'not-exist.jpg')
        res = export_chats(S(missing), ['u1'], ['html'], None, None, td,
                           archive=True)
        html = [f for f in res['files'] if f.endswith('.html')][0]
        text = open(html, encoding='utf-8').read()
        assert '[媒体缺失]' in text, 'HTML 应标记缺失媒体'
        assert 'file:///' not in text, '归档模式不应回退绝对路径'
        manifest = json.load(open(os.path.join(res['dir'], '张三', 'manifest.json'),
                                  encoding='utf-8'))
        assert manifest['missing_media'] == [missing], manifest
    print('  ok  归档缺失媒体标记与清单')


def test_html_preserves_newlines():
    class S(FakeStore):
        def messages(self, username, since=None, until=None):
            m = super().messages(username)
            m[0]['text'] = '第一行\n第二行'
            return m

    with tempfile.TemporaryDirectory() as td:
        res = export_chats(S({'u1': '张三'}), ['u1'], ['html'], None, None, td,
                           archive=True)
        html = [f for f in res['files'] if f.endswith('.html')][0]
        text = open(html, encoding='utf-8').read()
        assert 'white-space:pre-wrap' in text, '气泡应保留换行'
        assert '第一行\n第二行' in text, text[:500]
    print('  ok  HTML 气泡保留换行')


def test_file_attachment_exported_and_clickable():
    class S(FakeStore):
        def __init__(self, src):
            super().__init__({'u1': '张三'})
            self.src = src

        def messages(self, username, since=None, until=None):
            return [{
                'local_id': 1, 'ts': 1767225600, 'time': '2026-01-01 00:00:00',
                'type': 'app', 'kind': 'file', 'sender': '张三',
                'text': '[文件] 报表.xlsx', 'media': '',
                'content': {'kind': 'file', 'title': '报表.xlsx', 'size': '10 B',
                            'file_path': self.src, 'file_name': '报表.xlsx'},
            }]

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, '报表.xlsx')
        open(src, 'wb').write(b'x' * 10)
        res = export_chats(S(src), ['u1'], ['html'], None, None, td,
                           archive=True)
        html = [f for f in res['files'] if f.endswith('.html')][0]
        text = open(html, encoding='utf-8').read()
        assert 'a class="card file-card"' in text, text[:800]
        assert 'download="报表.xlsx"' in text, text[:800]
        files = os.listdir(os.path.join(os.path.dirname(html), 'files'))
        assert len(files) == 1 and files[0].endswith('报表.xlsx'), files
    print('  ok  附件复制进归档并可点击')


def test_sticker_and_voice_export():
    class S(FakeStore):
        def __init__(self, sticker, voice):
            super().__init__({'u1': '张三'})
            self.sticker = sticker
            self.voice = voice

        def messages(self, username, since=None, until=None):
            return [
                {'local_id': 1, 'ts': 1767225600, 'time': '2026-01-01 00:00:00',
                 'type': 'sticker', 'kind': 'sticker', 'sender': '张三',
                 'text': '[表情]', 'media': self.sticker,
                 'content': {'kind': 'sticker', 'md5': 'a' * 32}},
                {'local_id': 2, 'ts': 1767225660, 'time': '2026-01-01 00:01:00',
                 'type': 'voice', 'kind': 'voice', 'sender': '张三',
                 'text': '[语音]', 'media': self.voice, 'content': {}},
            ]

    with tempfile.TemporaryDirectory() as td:
        sticker = os.path.join(td, 's.gif')
        open(sticker, 'wb').write(b'GIF89a' + b'\0' * 8)
        voice = os.path.join(td, 'v.wav')
        open(voice, 'wb').write(b'RIFF' + b'\0' * 8)
        res = export_chats(S(sticker, voice), ['u1'], ['html'], None, None, td,
                           archive=True)
        html = [f for f in res['files'] if f.endswith('.html')][0]
        text = open(html, encoding='utf-8').read()
        assert '<img class="sticker-img"' in text, text[:800]
        assert text.count('<img class="sticker-img"') == 1, '表情不应重复输出'
        assert '下载语音' in text, text[:800]
        assert len(os.listdir(os.path.join(os.path.dirname(html), 'images'))) == 1
        assert len(os.listdir(os.path.join(os.path.dirname(html), 'audio'))) == 1
    print('  ok  表情可放大、语音可下载')


def test_export_downloads_stickers_without_prepare():
    from unittest import mock

    class S(FakeStore):
        def __init__(self, sticker_dir):
            super().__init__({'u1': '张三'})
            self.sticker_dir = sticker_dir

        def messages(self, username, since=None, until=None):
            return [{
                'local_id': 1, 'ts': 1767225600, 'time': '2026-01-01 00:00:00',
                'type': 'sticker', 'kind': 'sticker', 'sender': '张三',
                'text': '[表情]', 'media': '',
                'content': {'kind': 'sticker', 'md5': 'c' * 32,
                            'cdnurl': 'http://wxapp.tc.qq.com/x'},
            }]

    with tempfile.TemporaryDirectory() as td:
        sdir = os.path.join(td, 'stickers')

        def fake_download(tasks, out_dir, **kw):
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, 'c' * 32 + '.gif')
            open(path, 'wb').write(b'GIF89a' + b'\0' * 8)
            return {'total': 1, 'ok': 1, 'skipped': 0, 'failed': 0,
                    'files': [path]}

        with mock.patch('app.core.export.stickers.download_many', fake_download):
            res = export_chats(S(sdir), ['u1'], ['html'], None, None, td,
                               archive=True)
        html = [f for f in res['files'] if f.endswith('.html')][0]
        text = open(html, encoding='utf-8').read()
        assert '<img class="sticker-img"' in text, text[:800]
        assert len(os.listdir(os.path.join(os.path.dirname(html), 'images'))) == 1
    print('  ok  未准备时导出自动下载表情')


def test_other_platform_share_cards_clickable():
    class S(FakeStore):
        def messages(self, username, since=None, until=None):
            return [
                {'local_id': 1, 'ts': 1767225600, 'time': '2026-01-01 00:00:00',
                 'type': 'app', 'kind': 'video_share', 'sender': '张三',
                 'text': '[视频] B 站视频', 'media': '',
                 'content': {'kind': 'video_share', 'title': 'B 站视频',
                             'url': 'https://b23.tv/sm67peh'}},
                {'local_id': 2, 'ts': 1767225660, 'time': '2026-01-01 00:01:00',
                 'type': 'app', 'kind': 'miniprogram', 'sender': '张三',
                 'text': '[小程序] 电子钥匙', 'media': '',
                 'content': {'kind': 'miniprogram', 'title': '电子钥匙',
                             'url': 'https://mp.weixin.qq.com/x'}},
                {'local_id': 3, 'ts': 1767225720, 'time': '2026-01-01 00:02:00',
                 'type': 'app', 'kind': 'music', 'sender': '张三',
                 'text': '[音乐] 歌曲', 'media': '',
                 'content': {'kind': 'music', 'title': '歌曲',
                             'url': 'https://y.music.163.com/m/song?id=1'}},
            ]

    with tempfile.TemporaryDirectory() as td:
        res = export_chats(S({'u1': '张三'}), ['u1'], ['html'], None, None, td,
                           archive=True)
        html = [f for f in res['files'] if f.endswith('.html')][0]
        text = open(html, encoding='utf-8').read()
        assert 'href="https://b23.tv/sm67peh"' in text, text[:1000]
        assert 'href="https://mp.weixin.qq.com/x"' in text, text[:1000]
        assert 'href="https://y.music.163.com/m/song?id=1"' in text, text[:1000]
        assert text.count('card card-link') >= 3, text.count('card card-link')
        # B 站视频卡片提供标题搜索与复制标题工具
        assert 'search.bilibili.com/all?keyword=' in text, text[:1200]
        assert '搜索标题' in text and '复制标题' in text, text[:1200]
    print('  ok  B站/小程序/音乐分享卡片可点击')


def test_video_short_link_expired_and_resolved():
    class S(FakeStore):
        def messages(self, username, since=None, until=None):
            return [
                {'local_id': 1, 'ts': 1767225600, 'time': '2026-01-01 00:00:00',
                 'type': 'app', 'kind': 'video_share', 'sender': '张三',
                 'text': '[视频] 失效视频', 'media': '',
                 'content': {'kind': 'video_share', 'title': '失效视频',
                             'url': 'https://b23.tv/dead',
                             'link_expired': True,
                             'search_url': ('https://search.bilibili.com/all?'
                                            'keyword=%E5%A4%B1%E6%95%88%E8%A7%86%E9%A2%91')}},
                {'local_id': 2, 'ts': 1767225660, 'time': '2026-01-01 00:01:00',
                 'type': 'app', 'kind': 'video_share', 'sender': '张三',
                 'text': '[视频] 正常视频', 'media': '',
                 'content': {'kind': 'video_share', 'title': '正常视频',
                             'url': 'https://b23.tv/good',
                             'resolved_url': 'https://www.bilibili.com/video/BV1good'}},
            ]

    with tempfile.TemporaryDirectory() as td:
        res = export_chats(S({'u1': '张三'}), ['u1'], ['html'], None, None, td,
                           archive=True)
        html = [f for f in res['files'] if f.endswith('.html')][0]
        text = open(html, encoding='utf-8').read()
        assert 'href="https://search.bilibili.com/all?keyword=%E5%A4%B1%E6%95%88' in text, text
        assert '原短链已失效 · 点击按标题搜索' in text, text
        assert 'href="https://www.bilibili.com/video/BV1good"' in text, text
        assert '已解析为视频直链' in text, text
        assert 'class="copy-title"' in text and 'data-copy="失效视频"' in text, text
    print('  ok  失效短链改搜索、有效短链用直链、复制标题按钮')


def test_double_escaped_url_in_text_cleaned():
    class S(FakeStore):
        def messages(self, username, since=None, until=None):
            m = super().messages(username)[0]
            m['text'] = ('看这个 https://b23.tv/X?a=1&amp;amp;b=2'
                         '&lt;/url&gt;')
            return [m]

    with tempfile.TemporaryDirectory() as td:
        res = export_chats(S({'u1': '张三'}), ['u1'], ['html'], None, None, td,
                           archive=True)
        html = [f for f in res['files'] if f.endswith('.html')][0]
        text = open(html, encoding='utf-8').read()
        assert '&amp;amp;' not in text, '不应残留双重转义'
        assert '&lt;/url&gt;' not in text, '不应残留 XML 尾巴'
        assert 'href="https://b23.tv/X?a=1&amp;b=2"' in text, text[:1000]
    print('  ok  双重转义链接清洗')


def test_transfer_and_link_html():
    class S(FakeStore):
        def messages(self, username, since=None, until=None):
            return [
                {'local_id': 1, 'ts': 1767225600, 'time': '2026-01-01 00:00:00',
                 'type': 'app', 'kind': 'transfer', 'sender': '张三',
                 'text': '[转账] ￥88.00', 'media': '',
                 'content': {'kind': 'transfer', 'amount': '￥88.00',
                             'memo': '午饭', 'status': '已收款'}},
                {'local_id': 2, 'ts': 1767225660, 'time': '2026-01-01 00:01:00',
                 'type': 'app', 'kind': 'link', 'sender': '张三',
                 'text': '[链接] 文章', 'media': '',
                 'content': {'kind': 'link', 'title': '文章',
                             'url': 'https://example.com/a?b=1&c=2'}},
            ]

    with tempfile.TemporaryDirectory() as td:
        res = export_chats(S({'u1': '张三'}), ['u1'], ['html'], None, None, td,
                           archive=True)
        html = [f for f in res['files'] if f.endswith('.html')][0]
        text = open(html, encoding='utf-8').read()
        assert '￥88.00' in text and '午饭' in text and '已收款' in text, text[:800]
        assert 'href="https://example.com/a?b=1&amp;c=2"' in text, text[:800]
    print('  ok  转账明细与链接跳转')


def test_safe_name_windows_reserved():
    assert _safe_name('CON') == '_CON'
    assert _safe_name('a/b:c*') == 'a_b_c_'
    assert _safe_name('name. ') == 'name'
    print('  ok  Windows 文件名清洗')


def main():
    test_one_chat_failure_does_not_abort_batch()
    test_flat_mode_same_name_not_overwritten()
    test_missing_media_marked()
    test_html_preserves_newlines()
    test_file_attachment_exported_and_clickable()
    test_sticker_and_voice_export()
    test_export_downloads_stickers_without_prepare()
    test_other_platform_share_cards_clickable()
    test_video_short_link_expired_and_resolved()
    test_double_escaped_url_in_text_cleaned()
    test_transfer_and_link_html()
    test_safe_name_windows_reserved()
    print('导出容错测试全部通过')


if __name__ == '__main__':
    main()
