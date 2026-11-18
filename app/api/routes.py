# -*- coding: utf-8 -*-
"""FastAPI 接口"""
import hmac
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import __version__
from app.config import (BASE_DIR, load_config, save_config, account_paths,
                        export_dir_display)
from app.core import discovery, keys, decrypt, media, prepare, tools
from app.core.export import ChatStore, export_chats
from app.core.jobs import JobManager, JobBusy

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DIST = BASE_DIR / 'webui' / 'dist'


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _within(path: str, roots) -> bool:
    """路径必须位于某个允许目录内（按目录边界比较，防止前缀绕过）"""
    real = _norm(path)
    for root in roots:
        if not root:
            continue
        base = _norm(root)
        if real == base or real.startswith(base + os.sep):
            return True
    return False


def _file_roots(cfg: dict) -> list:
    """允许通过 /api/file 读取的目录（仅媒体缓存与导出结果）"""
    return [cfg.get('media_dir'), cfg.get('export_dir')]


def _open_roots(cfg: dict) -> list:
    """允许用系统程序打开的目录（仅媒体缓存与导出结果）"""
    return [cfg.get('media_dir'), cfg.get('export_dir')]


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


class PrepareBody(BaseModel):
    account: str
    targets: list[str]
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
        video_playback_dir=str(Path(paths['images']).parent / 'videos_h264'),
        ffmpeg=cfg.get('ffmpeg', 'ffmpeg'))


def account_state(cfg, account):
    paths = account_paths(cfg, account['folder'])
    keys_file = Path(paths['data']) / 'keys.json'
    data_root = Path(paths['data'])
    core_ready = (data_root / 'session' / 'session.db').exists() and \
        (data_root / 'contact' / 'contact.db').exists()
    msg_dir = data_root / 'message'
    messages_ready = any(msg_dir.glob('message_*.db')) and any(msg_dir.glob('media_*.db'))
    decrypted = messages_ready  # 兼容旧字段
    info = {'wxid': account['username'], 'nickname': ''}
    if decrypted:
        try:
            store = make_store(cfg, account)
            info = store.self_info()
            if not info.get('nickname'):
                info['nickname'] = account['username']
        except Exception:
            pass
    # 已准备（第 4 步）的会话列表：落盘保存，重启/刷新后仍可继续导出
    prepared_targets = []
    try:
        record = json.loads((data_root / 'prepared.json').read_text(encoding='utf-8'))
        prepared_targets = [t for t in record.get('targets', []) if isinstance(t, str)]
    except (OSError, ValueError, AttributeError):
        prepared_targets = []
    return {
        **account,
        'nickname': info.get('nickname') or account['username'],
        'has_keys': keys_file.exists(),
        'core_ready': core_ready,
        'messages_ready': messages_ready,
        'decrypted': decrypted,
        'prepared_targets': prepared_targets,
        'data_dir': paths['data'],
        'images_dir': paths['images'],
        'voices_dir': paths['voices'],
    }


def create_app(token: str = ''):
    tools.ensure_tools_on_path()
    app = FastAPI(title='微信聊天记录导出', version=__version__)
    mgr = JobManager(log_file=Path(BASE_DIR) / '运行日志.log')
    app.state.mgr = mgr
    app.state.cfg = load_config()

    def cfg():
        return app.state.cfg

    def start_job(kind, fn):
        try:
            return {'job': mgr.start(kind, fn)}
        except JobBusy as e:
            raise HTTPException(409, str(e))

    @app.middleware('http')
    async def guard(request: Request, call_next):
        """API 鉴权 + 防 DNS rebinding（静态页面本身不拦截）"""
        if token and request.url.path.startswith('/api'):
            supplied = (request.headers.get('x-auth-token')
                        or request.query_params.get('token') or '')
            if not hmac.compare_digest(supplied, token):
                return JSONResponse({'detail': '未授权：访问令牌无效'}, status_code=401)
            host = (request.headers.get('host') or '').lower()
            if not (host.startswith('127.0.0.1') or host.startswith('localhost')
                    or host.startswith('[::1]')):
                return JSONResponse({'detail': '非法 Host'}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        return response

    @app.get('/api/bootstrap')
    def bootstrap():
        c = cfg()
        root = c.get('wechat_root') or discovery.detect_wechat_root()
        accounts = [account_state(c, a) for a in discovery.find_accounts(root)]
        return {
            'version': __version__,
            'wechat_root': root,
            'detected_root': discovery.detect_wechat_root(),
            'everything': discovery.everything_status(),
            'ffmpeg': media.ffmpeg_status(c.get('ffmpeg', 'ffmpeg')),
            'wechat_version': discovery.detect_wechat_version(),
            'weixin_running': discovery.weixin_running(),
            'accounts': accounts,
            'export_dir': c['export_dir'],
            'export_dir_display': export_dir_display(c['export_dir']),
            'last_account': c.get('last_account', ''),
        }

    @app.post('/api/config')
    def set_config(body: ConfigBody):
        data = body.model_dump()
        for key in ('wechat_root', 'export_dir'):
            val = data.get(key)
            if val and not os.path.isdir(val):
                raise HTTPException(400, f'{key} 不是有效目录：{val}')
        c = cfg()
        for k, v in data.items():
            if v is not None:
                c[k] = v
        save_config(c)
        return {'ok': True}

    @app.post('/api/locate-wechat')
    def locate_wechat():
        """用 Everything（或本地扫描）快速定位微信数据目录"""
        return discovery.locate_wechat_roots()

    @app.post('/api/pick-folder')
    def pick_folder():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.askdirectory(
                title='选择微信数据目录或其上级目录（会自动递归查找 wxid 账号）')
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
            job.update(2, '正在读取微信进程内存以提取密钥...')
            found, meta = keys.extract_keys(
                acc['db_dir'],
                progress=lambda p, m='': job.update(5 + int(p * 0.65), m))
            if not found:
                raise RuntimeError(meta.get('message') or meta.get('error') or '未找到密钥')
            Path(paths['data']).mkdir(parents=True, exist_ok=True)
            (Path(paths['data']) / 'keys.json').write_text(
                json.dumps({'meta': meta, 'keys': found}, ensure_ascii=False, indent=2),
                encoding='utf-8')
            job.update(70, '密钥已保存，正在建立会话索引...')
            core = decrypt.decrypt_all(
                acc['db_dir'], paths['data'], found,
                only_rels=decrypt.CORE_DB_RELS,
                progress=lambda p, m='': job.update(70 + int(p * 0.3), m))
            job.update(100, f"模式 {meta.get('mode')}，命中 {len(found)} 个库，会话索引就绪")
            return {'mode': meta.get('mode'), 'count': len(found),
                    'missing': meta.get('missing', []), 'stats': meta.get('stats'),
                    'core': core}

        return start_job('keys', run)

    @app.post('/api/core')
    def start_core(body: AccountBody):
        """解密会话索引与消息库（第 3 步加载会话、预览用）"""
        c = cfg()
        acc = get_account(c, body.account)
        paths = account_paths(c, acc['folder'])
        keys_file = Path(paths['data']) / 'keys.json'
        if not keys_file.exists():
            raise HTTPException(400, '请先提取密钥')

        def run(job):
            data = json.loads(keys_file.read_text(encoding='utf-8'))
            rels = decrypt.chat_db_rels(acc['db_dir'])
            missing_keys = [r for r in rels if r not in data['keys']]
            job.update(2, '正在解密会话索引与消息库...')
            res = decrypt.decrypt_all(
                acc['db_dir'], paths['data'], data['keys'],
                only_rels=rels,
                progress=lambda p, m='': job.update(2 + int(p * 0.96), m))
            res['missing_keys'] = missing_keys
            failed = [r['rel'] for r in res['results']
                      if r['status'] not in ('ok', 'skipped')]
            res['failed_dbs'] = failed
            if missing_keys:
                job.update(100, f"会话数据就绪，但有 {len(missing_keys)} 个消息库缺少密钥"
                                f"（{', '.join(missing_keys[:3])}），请重新提取密钥")
            elif failed:
                job.update(100, f"会话数据就绪，但 {len(failed)} 个库解密失败"
                                f"（{', '.join(failed[:3])}）")
            else:
                job.update(100, f"会话数据就绪（成功 {res['ok']}，跳过 {res['skipped']}）")
            return res

        return start_job('core', run)

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
                progress=lambda p, m='': job.update(2 + int(p * 0.95), m))
            job.update(100, f"成功 {res['ok']}，跳过 {res['skipped']}，失败 {res['failed']}")
            return res

        return start_job('decrypt', run)

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
            job.update(1, '正在分析已解密文件...')
            result = media.prepare_media(
                attach_dir=attach,
                images_dir=paths['images'],
                voices_dir=paths['voices'],
                media_db=str(db),
                wxid=acc['username'],
                codes=codes,
                workers=body.workers,
                do_images=body.images,
                do_hevc=body.hevc,
                do_voices=body.voices,
                do_videos=body.videos,
                video_roots=[os.path.join(acc['base_dir'], 'msg', 'video'),
                             os.path.join(acc['base_dir'], 'msg', 'attach')],
                video_cache=video_cache,
                progress=lambda p, m='': job.update(p, m),
            )
            job.update(100, '媒体处理完成')
            return result

        return start_job('media', run)

    @app.post('/api/prepare')
    def start_prepare(body: PrepareBody):
        """按所选会话准备媒体数据（五步流程第 4 步）"""
        c = cfg()
        acc = get_account(c, body.account)
        paths = account_paths(c, acc['folder'])
        keys_file = Path(paths['data']) / 'keys.json'
        if not keys_file.exists():
            raise HTTPException(400, '请先提取密钥')
        if not body.targets:
            raise HTTPException(400, '请先选择会话')

        def run(job):
            data = json.loads(keys_file.read_text(encoding='utf-8'))
            rels = decrypt.chat_db_rels(acc['db_dir'])
            missing_keys = [r for r in rels if r not in data['keys']]
            job.update(1, '正在刷新会话数据...')
            refresh = decrypt.decrypt_all(
                acc['db_dir'], paths['data'], data['keys'],
                only_rels=rels,
                progress=lambda p, m='': job.update(1 + int(p * 0.09), m))
            failed_dbs = [r['rel'] for r in refresh['results']
                          if r['status'] not in ('ok', 'skipped')]
            store = make_store(c, acc)
            job.update(10, f'正在准备 {len(body.targets)} 个所选会话...')
            result = prepare.prepare_selected_media(
                store, body.targets,
                os.path.join(acc['base_dir'], 'msg', 'attach'),
                acc['username'], discovery.find_kvcomm_codes(),
                c.get('ffmpeg', 'ffmpeg'), workers=body.workers,
                progress=lambda p, m='': job.update(10 + int(p * 0.9), m))
            problems = []
            if missing_keys:
                problems.append(
                    f'有 {len(missing_keys)} 个消息库缺少密钥（'
                    + ', '.join(missing_keys[:3]) + '），历史消息可能缺失，请重新提取密钥')
            if failed_dbs:
                problems.append(
                    f'{len(failed_dbs)} 个消息库解密失败（'
                    + ', '.join(failed_dbs[:3]) + '），历史消息可能缺失')
            result['missing_keys'] = missing_keys
            result['decrypt_failed'] = failed_dbs
            for key, label in (('images', '图片'), ('wxam', 'WxAM'),
                               ('voices', '语音')):
                st = result.get(key) or {}
                if st.get('error'):
                    problems.append(f'{label}: {st["error"]}')
                elif st.get('failed'):
                    problems.append(f'{label}失败 {st["failed"]} 个')
            video = result.get('videos') or {}
            if video.get('probe_failed'):
                problems.append(f'视频编码探测失败 {video["probe_failed"]} 个（FFmpeg 可能缺失）')
            if video.get('failed'):
                problems.append(f'视频转码失败 {video["failed"]} 个')
            # 记录已准备的会话：重启程序或刷新页面后仍可直接进入导出
            try:
                (Path(paths['data']) / 'prepared.json').write_text(
                    json.dumps({'targets': body.targets,
                                'ts': datetime.now().isoformat(timespec='seconds'),
                                'problems': problems},
                               ensure_ascii=False), encoding='utf-8')
            except OSError:
                pass
            if problems:
                result['problems'] = problems
                job.update(100, '准备完成但有异常：' + '；'.join(problems[:4]))
            else:
                job.update(100, '所选会话数据准备完成')
            return result

        return start_job('prepare', run)

    @app.get('/api/sessions')
    def sessions(account: str):
        c = cfg()
        acc = get_account(c, account)
        store = make_store(c, acc)
        items = store.sessions_with_counts()
        items.sort(key=lambda x: (x['count'] == 0, -x['count']))
        return {'sessions': items}

    @app.post('/api/sessions/refresh')
    def start_sessions_refresh(body: AccountBody):
        """解析会话列表（后台任务，带进度）；完成后返回完整列表

        数据量大时首屏统计消息数可能持续较久，由前端轮询任务进度并显示进度条。
        """
        c = cfg()
        acc = get_account(c, body.account)

        def run(job):
            store = make_store(c, acc)
            items = store.sessions_with_counts(
                progress=lambda p, m='': job.update(p, m))
            items.sort(key=lambda x: (x['count'] == 0, -x['count']))
            return {'sessions': items}

        return start_job('sessions', run)

    @app.get('/api/chat')
    def chat(account: str, username: str, limit: int = 100,
             before: int | None = None, before_id: int | None = None,
             before_sort: int | None = None):
        if limit < 1 or limit > 500:
            raise HTTPException(400, 'limit 必须在 1-500 之间')
        c = cfg()
        acc = get_account(c, account)
        store = make_store(c, acc)
        msgs = store.messages(username, limit=limit, before_ts=before,
                              before_id=before_id, before_sort=before_sort)
        return {'messages': msgs, 'has_more': len(msgs) >= limit}

    @app.post('/api/export')
    def start_export(body: ExportBody):
        allowed = {'html', 'txt', 'json', 'csv'}
        bad = set(body.formats or []) - allowed
        if not body.formats or bad:
            raise HTTPException(400, f'不支持的导出格式：{sorted(bad) or "空"}')
        if not body.targets:
            raise HTTPException(400, '请先选择要导出的会话')
        if body.since:
            try:
                datetime.strptime(body.since, '%Y-%m-%d')
            except ValueError:
                raise HTTPException(400, '起始日期格式应为 YYYY-MM-DD')
        if body.until:
            try:
                datetime.strptime(body.until, '%Y-%m-%d')
            except ValueError:
                raise HTTPException(400, '结束日期格式应为 YYYY-MM-DD')
        if body.since and body.until and body.since > body.until:
            raise HTTPException(400, '起始日期不能晚于结束日期')
        c = cfg()
        acc = get_account(c, body.account)

        def run(job):
            store = make_store(c, acc)
            if store.video_roots:
                job.update(1, '正在更新视频索引...')
                store.refresh_video_index(
                    progress=lambda p: job.update(
                        1 + int(p * 0.06), f'正在更新视频索引… {p}%'))
            job.update(8, f'导出 {len(body.targets)} 个会话（视频按需转码）...')
            result = export_chats(
                store, body.targets, body.formats,
                body.since, body.until, c['export_dir'],
                archive=body.archive,
                progress=lambda p, m='': job.update(8 + int(p * 0.9), m))
            errors = result.get('errors') or []
            if errors and not result.get('files'):
                detail = '；'.join(f"{e['name']}: {e['error']}"
                                  for e in errors[:3])
                raise RuntimeError(f'全部会话导出失败：{detail}')
            if errors:
                detail = '；'.join(f"{e['name']}: {e['error']}"
                                  for e in errors[:3])
                job.update(99, f"{len(errors)} 个会话失败：{detail}")
            job.update(100, f"已生成 {len(result['files'])} 个文件")
            return result

        return start_job('export', run)

    @app.get('/api/jobs/{job_id}')
    def job(job_id: str):
        data = mgr.get(job_id)
        if not data:
            raise HTTPException(404, '任务不存在')
        return data

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel_job(job_id: str):
        if not mgr.cancel(job_id):
            raise HTTPException(404, '任务不存在或已结束')
        return {'ok': True}

    @app.post('/api/open-folder')
    @app.post('/api/open-path')
    def open_folder(body: dict):
        path = body.get('path') or cfg()['export_dir']
        if not _within(path, _open_roots(cfg())):
            raise HTTPException(403, '路径不在允许范围内')
        try:
            os.startfile(path)  # noqa: S606
            return {'ok': True}
        except Exception as e:  # noqa: BLE001
            return {'ok': False, 'error': str(e)}

    @app.get('/api/file')
    def get_file(path: str):
        from fastapi.responses import FileResponse
        real = os.path.realpath(path)
        if not _within(real, _file_roots(cfg())):
            raise HTTPException(403, '路径不在允许范围内')
        if not os.path.isfile(real):
            raise HTTPException(404, '文件不存在')
        return FileResponse(real)

    if DIST.exists():
        app.mount('/', StaticFiles(directory=str(DIST), html=True), name='webui')

    return app
