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
    test_safe_name_windows_reserved()
    print('导出容错测试全部通过')


if __name__ == '__main__':
    main()
