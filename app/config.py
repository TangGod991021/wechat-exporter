# -*- coding: utf-8 -*-
"""配置管理：所有路径集中在这里，避免散落硬编码"""
import json
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    # 打包后：config.json 与 data/media/exports 放在 exe 同级，便于整个文件夹拷贝使用
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG_FILE = BASE_DIR / 'config.json'

DEFAULTS = {
    'wechat_root': '',                       # 微信数据目录（含 wxid_xxx 文件夹）
    'data_dir': str(BASE_DIR / 'data'),      # 解密后的数据库
    'export_dir': str(BASE_DIR / 'exports'), # 导出结果
    'media_dir': str(BASE_DIR / 'media'),    # 图片 / 语音
    'ffmpeg': 'ffmpeg',
    'last_account': '',
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding='utf-8')))
        except Exception:
            pass
    return cfg


def save_config(cfg: dict):
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')


def account_paths(cfg: dict, folder: str) -> dict:
    """返回某账号的解密产物目录"""
    base = Path(cfg['data_dir']) / folder
    media = Path(cfg['media_dir']) / folder
    return {
        'data': str(base),
        'images': str(media / 'images'),
        'voices': str(media / 'voices'),
    }
