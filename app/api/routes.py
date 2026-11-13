# -*- coding: utf-8 -*-
"""FastAPI 接口"""
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import __version__
from app.config import load_config, save_config, account_paths
from app.core import discovery, keys, decrypt, media
from app.core.export import ChatStore, export_chats
from app.core.jobs import JobManager

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DIST = BASE_DIR / 'webui' / 'dist'


class ConfigBody(BaseModel):
    wechat_root: str | None = None
    export_dir: str | None = None
    ffmpeg: str | None = None
    last_account: str | None = None


class AccountBody(BaseModel):
    account: str


class ExportBody(BaseModel):
    account: str
    targets: list[str]
    formats: list[str] = ['html', 'txt']
    since: str | None = None
    until: str | None = None
    archive: bool = True


class MediaBody(BaseModel):
    account: str
    images: bool = True
    hevc: bool = True
    voices: bool = True
    videos: bool = True
    workers: int | None = None


def get_account(cfg, folder):
    root = cfg.get('wechat_root') or discovery.detect_wechat_root()
    accounts = discovery.find_accounts(root)
    for a in accounts:
        if a['folder'] == folder:
            return a
    raise HTTPException(404, f'账号不存在: {folder}')


def make_store(cfg, account):
    paths = account_paths(cfg, account['folder'])
    base = account['base_dir']
    return ChatStore(
        paths['data'], paths['images'], paths['voices'], account['username'],
        video_roots=[os.path.join(base, 'msg', 'video'),
                     os.path.join(base, 'msg', 'attach')],
        video_cache=str(Path(paths['images']).parent / 'video_index.json'),
        video_playback_dir=str(Path(paths['images']).parent / 'videos_h264'))


def account_state(cfg, account):
    paths = account_paths(cfg, account['folder'])
    keys_file = Path(paths['data']) / 'keys.json'
    decrypted = (Path(paths['data']) / 'session' / 'session.db').exists()
    info = {'wxid': account['username'], 'nickname': ''}
    if decrypted:
        try:
            store = make_store(cfg, account)
            info = store.self_info()
            if not info.get('nickname'):
                info['nickname'] = account['username']
        except Exception:
            pass
    images = Path(paths['images'])
    voices = Path(paths['voices'])
    img_count = sum(1 for _ in images.rglob('*')
                    if _.suffix.lower() in ('.jpg', '.png', '.webp', '.gif')) if images.exists() else 0
    voice_count = sum(1 for _ in voices.rglob('*.wav')) if voices.exists() else 0
    video_cache = Path(paths['images']).parent / 'video_index.json'
    video_count = 0
    if video_cache.exists():
        try:
            from app.core.media import load_video_index
            video_count = len(load_video_index(str(video_cache)))
        except Exception:
            video_count = 0
    return {
        **account,
        'nickname': info.get('nickname') or account['username'],
        'has_keys': keys_file.exists(),
        'decrypted': decrypted,
        'images_decoded': img_count,
        'voices_decoded': voice_count,
        'videos_indexed': video_count,
        'data_dir': paths['data'],
        'images_dir': paths['images'],
        'voices_dir': paths['voices'],
    }


def create_app():
    app = FastAPI(title='微信聊天记录导出', version=__version__)
    app.add_middleware(
        CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
    mgr = JobManager()
    app.state.mgr = mgr
    app.state.cfg = load_config()

    def cfg():
        return app.state.cfg

    @app.get('/api/bootstrap')
    def bootstrap():
        c = cfg()
        root = c.get('wechat_root') or discovery.detect_wechat_root()
        accounts = [account_state(c, a) for a in discovery.find_accounts(root)]
        return {
            'version': __version__,
            'wechat_root': root,
            'detected_root': discovery.detect_wechat_root(),
            'wechat_version': discovery.detect_wechat_version(),
            'weixin_running': discovery.weixin_running(),
            'accounts': accounts,
            'export_dir': c['export_dir'],
            'last_account': c.get('last_account', ''),
        }

    @app.post('/api/config')
    def set_config(body: ConfigBody):
        c = cfg()
        for k, v in body.model_dump().items():
            if v is not None:
                c[k] = v
        save_config(c)
        return {'ok': True}

    @app.post('/api/pick-folder')
    def pick_folder():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.askdirectory(title='选择微信数据目录（含 wxid_xxx 文件夹）')
            root.destroy()
            return {'path': path or ''}
        except Exception as e:  # noqa: BLE001
            return {'path': '', 'error': str(e)}

    @app.post('/api/keys')
    def start_keys(body: AccountBody):
        c = cfg()
        acc = get_account(c, body.account)
        paths = account_paths(c, acc['folder'])

        def run(job):
            job.update(5, '正在扫描微信内存...')
            found, meta = keys.extract_keys(
                acc['db_dir'], progress=lambda p: job.update(5 + int(p * 0.9)))
            if not found:
                raise RuntimeError(meta.get('message') or meta.get('error') or '未找到密钥')
            Path(paths['data']).mkdir(parents=True, exist_ok=True)
            (Path(paths['data']) / 'keys.json').write_text(
                json.dumps({'meta': meta, 'keys': found}, ensure_ascii=False, indent=2),
                encoding='utf-8')
            job.update(100, f"模式 {meta.get('mode')}，命中 {len(found)} 个库")
            return {'mode': meta.get('mode'), 'count': len(found),
                    'missing': meta.get('missing', []), 'stats': meta.get('stats')}

        return {'job': mgr.start('keys', run)}

    @app.post('/api/decrypt')
    def start_decrypt(body: AccountBody):
        c = cfg()
        acc = get_account(c, body.account)
        paths = account_paths(c, acc['folder'])
        keys_file = Path(paths['data']) / 'keys.json'
        if not keys_file.exists():
            raise HTTPException(400, '请先提取密钥')

        def run(job):
            data = json.loads(keys_file.read_text(encoding='utf-8'))
            job.update(2, f"解密 {len(data['keys'])} 个数据库...")
            res = decrypt.decrypt_all(
                acc['db_dir'], paths['data'], data['keys'],
                progress=lambda p: job.update(2 + int(p * 0.95)))
            job.update(100, f"成功 {res['ok']}，跳过 {res['skipped']}，失败 {res['failed']}")
            return res

        return {'job': mgr.start('decrypt', run)}

    @app.post('/api/media')
    def start_media(body: MediaBody):
        c = cfg()
        acc = get_account(c, body.account)
        paths = account_paths(c, acc['folder'])

        def run(job):
            attach = os.path.join(acc['base_dir'], 'msg', 'attach')
            codes = discovery.find_kvcomm_codes()
            db = Path(paths['data']) / 'message' / 'media_0.db'
            video_cache = str(Path(paths['images']).parent / 'video_index.json')
            video_playback_dir = str(Path(paths['images']).parent / 'videos_h264')
            job.update(1, '正在分析已解密文件...')
            result = media.prepare_media(
                attach_dir=attach,
                images_dir=paths['images'],
                voices_dir=paths['voices'],
                media_db=str(db),
                wxid=acc['username'],
                codes=codes,
                ffmpeg=c.get('ffmpeg', 'ffmpeg'),
                workers=body.workers,
                do_images=body.images,
                do_hevc=body.hevc,
                do_voices=body.voices,
                do_videos=body.videos,
                video_roots=[os.path.join(acc['base_dir'], 'msg', 'video'),
                             os.path.join(acc['base_dir'], 'msg', 'attach')],
                video_cache=video_cache,
                video_playback_dir=video_playback_dir,
                transcode_videos=body.videos,
                progress=lambda p, m='': job.update(p, m),
            )
            job.update(100, '媒体处理完成')
            return result

        return {'job': mgr.start('media', run)}

    @app.get('/api/sessions')
    def sessions(account: str):
        c = cfg()
        acc = get_account(c, account)
        store = make_store(c, acc)
        items = store.sessions()
        counts = {it['username']: store.message_count(it['username']) for it in items}
        for it in items:
            it['count'] = counts.get(it['username'], 0)
        items.sort(key=lambda x: (x['count'] == 0, -x['count']))
        return {'sessions': items}

    @app.get('/api/chat')
    def chat(account: str, username: str, limit: int = 100, before: int | None = None):
        c = cfg()
        acc = get_account(c, account)
        store = make_store(c, acc)
        msgs = store.messages(username, limit=limit, before_ts=before)
        return {'messages': msgs}

    @app.post('/api/export')
    def start_export(body: ExportBody):
        c = cfg()
        acc = get_account(c, body.account)

        def run(job):
            store = make_store(c, acc)
            job.update(2, f'导出 {len(body.targets)} 个会话...')
            result = export_chats(
                store, body.targets, body.formats,
                body.since, body.until, c['export_dir'],
                archive=body.archive,
                progress=lambda p, m='': job.update(p, m))
            job.update(100, f"已生成 {len(result['files'])} 个文件")
            return result

        return {'job': mgr.start('export', run)}

    @app.get('/api/jobs/{job_id}')
    def job(job_id: str):
        data = mgr.get(job_id)
        if not data:
            raise HTTPException(404, '任务不存在')
        return data

    @app.post('/api/open-folder')
    @app.post('/api/open-path')
    def open_folder(body: dict):
        path = body.get('path') or cfg()['export_dir']
        try:
            os.startfile(path)  # noqa: S606
            return {'ok': True}
        except Exception as e:  # noqa: BLE001
            return {'ok': False, 'error': str(e)}

    @app.get('/api/file')
    def get_file(path: str):
        from fastapi.responses import FileResponse
        real = os.path.realpath(path)
        c = cfg()
        allowed = [c.get('media_dir'), c.get('data_dir'), c.get('export_dir'),
                   c.get('wechat_root'), discovery.detect_wechat_root()]
        if not any(a and real.startswith(os.path.realpath(a)) for a in allowed):
            raise HTTPException(403, '路径不在允许范围内')
        if not os.path.isfile(real):
            raise HTTPException(404, '文件不存在')
        return FileResponse(real)

    if DIST.exists():
        app.mount('/', StaticFiles(directory=str(DIST), html=True), name='webui')

    return app
