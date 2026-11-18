# -*- coding: utf-8 -*-
"""配置管理：所有路径集中在这里，避免散落硬编码"""
import json
import os
import shutil
import sys
from pathlib import Path

from app.core import tools


def _default_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        # 打包后：config.json 与 data/media/exports 放在 exe 同级，便于整个文件夹拷贝使用
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _pick_base_dir() -> Path:
    """优先使用程序目录；只读位置（如 Program Files）回退到 %LOCALAPPDATA%"""
    base = _default_base_dir()
    try:
        base.mkdir(parents=True, exist_ok=True)
        probe = base / '.write_test'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
        return base
    except OSError:
        fallback = Path(os.environ.get('LOCALAPPDATA', str(base))) / 'WeChatExporter'
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return fallback


BASE_DIR = _pick_base_dir()
CONFIG_FILE = BASE_DIR / 'config.json'

DEFAULTS = {
    'wechat_root': '',                       # 微信数据目录（含 wxid_xxx 文件夹）
    'data_dir': str(BASE_DIR / 'data'),      # 解密后的数据库
    'export_dir': 'exports',                 # 导出结果：相对 exe 目录（同级 exports/）
    'media_dir': str(BASE_DIR / 'media'),    # 图片 / 语音
    'ffmpeg': 'ffmpeg',
    'last_account': '',
}


def _rel_to_base(value: str) -> str:
    """返回相对程序目录的 POSIX 路径；不在程序目录内时返回空串。"""
    try:
        path = Path(value)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except (ValueError, OSError):
        return ''


def export_dir_display(value: str) -> str:
    """用于界面展示：程序目录内显示相对路径（如 exports），否则原样返回。"""
    return _rel_to_base(value) or value


def _resolve_export_dir(value: str) -> str:
    """导出目录解析规则（默认相对 exe 目录的 exports/）。

    - 相对路径：相对程序目录（配置中默认保存 `exports`，移动整个文件夹后仍有效）
    - 程序目录内的绝对路径：也按相对路径解析
    - 程序目录外的绝对路径且存在：保持用户选择
    - 绝对路径不存在（从别的电脑复制过来的 config.json）：回退到默认目录
    """
    default = str(BASE_DIR / 'exports')
    if not value:
        return default
    path = Path(value)
    if not path.is_absolute():
        return str(BASE_DIR / path)
    rel = _rel_to_base(path)
    if rel:
        return str(BASE_DIR / rel)
    if path.exists():
        return str(path)
    return default


def _store_export_dir(value: str) -> str:
    """位于程序目录内时以相对路径保存，整个文件夹拷贝到别的电脑后仍可使用。"""
    return _rel_to_base(value) or value


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding='utf-8')))
        except Exception:
            # 损坏的配置备份保留，避免下次静默覆盖；使用默认值继续启动
            try:
                CONFIG_FILE.replace(CONFIG_FILE.with_suffix('.json.bad'))
            except OSError:
                pass
    cfg['export_dir'] = _resolve_export_dir(cfg.get('export_dir', ''))

    # 优先使用随包内置的 ffmpeg；配置里指向不存在的绝对路径时也回退到内置版本
    bundled = tools.bundled_ffmpeg()
    ffmpeg = cfg.get('ffmpeg') or 'ffmpeg'
    if bundled and (ffmpeg in ('ffmpeg', 'ffmpeg.exe')
                    or not (os.path.isfile(ffmpeg) or shutil.which(ffmpeg))):
        cfg['ffmpeg'] = bundled
    return cfg


def save_config(cfg: dict):
    """临时文件 + 原子替换，避免断电/并发写产生半截 JSON"""
    data = dict(cfg)
    if data.get('export_dir'):
        data['export_dir'] = _store_export_dir(data['export_dir'])
    tmp = CONFIG_FILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    os.replace(tmp, CONFIG_FILE)


def account_paths(cfg: dict, folder: str) -> dict:
    """返回某账号的解密产物目录"""
    base = Path(cfg['data_dir']) / folder
    media = Path(cfg['media_dir']) / folder
    return {
        'data': str(base),
        'images': str(media / 'images'),
        'voices': str(media / 'voices'),
    }
