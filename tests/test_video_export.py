# -*- coding: utf-8 -*-
"""导出时的按需视频转码测试（离线，使用临时文件与 mock）。"""
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core import media  # noqa: E402
from app.core.export import _apply_playback, _video_md5s  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def _touch(path, data=b'x'):
    with open(path, 'wb') as f:
        f.write(data)


def test_only_selected_videos_are_transcoded():
    with tempfile.TemporaryDirectory() as td:
        srcs = {}
        index = {}
        for name, md5 in (('a', 'a' * 32), ('b', 'b' * 32), ('c', 'c' * 32)):
            p = os.path.join(td, name + '.mp4')
            _touch(p, name.encode())
            srcs[name] = p
            index[md5] = p

        calls = []

        def fake_transcode(src, dst, ffmpeg):
            calls.append((os.path.basename(src), os.path.basename(dst)))
            _touch(dst, b'h264')
            return True

        cache = os.path.join(td, 'video_index.json')
        playback = os.path.join(td, 'videos_h264')
        with mock.patch.object(media, '_probe_codec', return_value='hevc'), \
                mock.patch.object(media, '_transcode_one',
                                  side_effect=fake_transcode):
            res = media.prepare_video_playback(
                index, cache, playback, only_md5s={'a' * 32})

        assert res['selected'] == 1, res
        assert res['transcoded'] == 1, res
        assert len(calls) == 1 and calls[0][0] == 'a.mp4', calls
        assert os.path.exists(os.path.join(playback, 'a' * 32 + '.mp4'))
        assert not os.path.exists(os.path.join(playback, 'b' * 32 + '.mp4'))

        # 第二次导出应命中缓存，不再转码
        calls.clear()
        with mock.patch.object(media, '_probe_codec', return_value='hevc'), \
                mock.patch.object(media, '_transcode_one',
                                  side_effect=fake_transcode):
            res2 = media.prepare_video_playback(
                index, cache, playback, only_md5s={'a' * 32})
        assert res2['transcoded'] == 0 and res2['skipped'] == 1, res2
        assert not calls, calls


def test_video_md5_collection_and_patch():
    video_md5 = 'd' * 32
    record_md5 = 'e' * 32
    msgs = [
        {'video_md5': video_md5, 'media': r'C:\src\a.mp4', 'content': {}},
        {'video_md5': '', 'media': '', 'content': {
            'records': [{'kind': 'video', 'video_md5': record_md5,
                         'media': r'C:\src\b.mp4'}]}},
        {'content': {'records': [{'kind': 'image', 'media': r'C:\src\c.jpg'}]}},
    ]
    assert _video_md5s(msgs) == {video_md5, record_md5}

    with tempfile.TemporaryDirectory() as td:
        _touch(os.path.join(td, video_md5 + '.mp4'), b'h264')
        # 仅第一个视频已转码，另一个保持原路径
        _apply_playback(msgs, td)
        assert msgs[0]['media'].endswith(video_md5 + '.mp4')
        assert msgs[1]['content']['records'][0]['media'] == r'C:\src\b.mp4'

    print('OK: 仅转码所选视频，且重复导出命中缓存')


if __name__ == '__main__':
    test_only_selected_videos_are_transcoded()
    test_video_md5_collection_and_patch()
    print('VIDEO EXPORT TESTS OK')
