# -*- coding: utf-8 -*-
"""按所选会话准备媒体数据（五步流程的第 4 步）"""
from app.core.export import collect_media_ids
from app.core.media import (default_workers, prepare_images, prepare_voices,
                            prepare_video_playback, prepare_wxam)


def _sub_progress(progress, start, end):
    def cb(p, m=''):
        if progress:
            progress(int(start + (end - start) * p / 100), m)
    return cb


def prepare_selected_media(store, targets, attach_dir, wxid, codes, ffmpeg,
                           workers=None, progress=None):
    """只处理 targets 中实际引用的图片 / 语音 / 视频。

    返回各类媒体的统计结果，单个阶段失败不会中断其它阶段。
    """
    workers = workers or default_workers()
    progress = progress or (lambda p, m='': None)
    stats = {}

    progress(0, '正在解析所选会话...')
    ids = collect_media_ids(store, targets, _sub_progress(progress, 0, 15))
    stats['selected'] = {
        'images': len(ids['images']),
        'voices': len(ids['voices']),
        'videos': len(ids['videos']),
    }

    index = {}
    stats['videos_indexed'] = 0
    if ids['videos']:
        progress(15, '正在更新视频索引...')
        index = store.refresh_video_index(
            progress=lambda p: progress(15 + int(p * 0.1), f'视频索引 {p}%'))
        stats['videos_indexed'] = len(index)

    if ids['images']:
        try:
            stats['images'] = prepare_images(
                attach_dir, store.images_dir, wxid, codes, workers=workers,
                only_md5s=ids['images'], progress=_sub_progress(progress, 25, 50))
        except Exception as e:  # noqa: BLE001
            stats['images'] = {'error': str(e)}
        try:
            stats['wxam'] = prepare_wxam(
                store.images_dir, workers=workers, only_md5s=ids['images'],
                progress=_sub_progress(progress, 50, 62))
        except Exception as e:  # noqa: BLE001
            stats['wxam'] = {'error': str(e)}
    else:
        stats['images'] = {'total': 0, 'ok': 0, 'skipped': 0, 'failed': 0}
        stats['wxam'] = {'total': 0, 'ok': 0, 'skipped': 0, 'failed': 0}
        progress(50, '所选会话没有图片')

    if ids['voices']:
        try:
            stats['voices'] = prepare_voices(
                store.media_db, store.voices_dir, workers=workers,
                only_messages=ids['voices'],
                progress=_sub_progress(progress, 62, 84))
        except Exception as e:  # noqa: BLE001
            stats['voices'] = {'error': str(e)}
    else:
        stats['voices'] = {'total': 0, 'ok': 0, 'skipped': 0, 'failed': 0}
        progress(84, '所选会话没有语音')

    video_index = {md5: src for md5, src in index.items() if md5 in ids['videos']}
    if video_index and store.video_playback_dir:
        stats['videos'] = prepare_video_playback(
            video_index, store.video_cache, store.video_playback_dir, ffmpeg,
            workers=workers, only_md5s=ids['videos'],
            progress=_sub_progress(progress, 84, 100))
    else:
        stats['videos'] = {'selected': 0, 'hevc': 0, 'transcoded': 0,
                           'skipped': 0, 'failed': 0}
        progress(100, '所选会话没有需要转码的视频')

    return stats
