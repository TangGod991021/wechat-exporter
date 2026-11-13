# -*- coding: utf-8 -*-
"""发现微信数据目录、账号、版本、图片密钥 code"""
import glob
import os
import re
import subprocess
import sys
from pathlib import Path

FOLDER_RE = re.compile(r'^(.+)_[0-9a-f]{4}$')
WECHAT_EXES = [
    r'C:\Program Files\Tencent\Weixin\Weixin.exe',
    r'C:\Program Files (x86)\Tencent\Weixin\Weixin.exe',
    r'C:\Program Files\Tencent\WeChat\WeChat.exe',
    r'C:\Program Files (x86)\Tencent\WeChat\WeChat.exe',
]


def candidate_roots():
    """常见的微信数据根目录"""
    home = Path(os.environ.get('USERPROFILE', 'C:/Users'))
    out = [
        home / 'Documents' / 'xwechat_files',
        Path('D:/xwechat_files'),
        Path('C:/xwechat_files'),
    ]
    return [str(p) for p in out]


def detect_wechat_root() -> str:
    for root in candidate_roots():
        if os.path.isdir(root):
            accounts = [d for d in os.listdir(root)
                        if os.path.isdir(os.path.join(root, d, 'db_storage'))]
            if accounts:
                return root
    return ''


def detect_wechat_version() -> str:
    for exe in WECHAT_EXES:
        if os.path.exists(exe):
            try:
                r = subprocess.run(
                    ['powershell', '-NoProfile', '-Command',
                     f"(Get-Item '{exe}').VersionInfo.FileVersion"],
                    capture_output=True, text=True, timeout=15)
                ver = (r.stdout or '').strip()
                if ver:
                    return ver
            except Exception:
                pass
    return ''


def account_username(folder: str) -> str:
    """wxid_xxx_9768 -> wxid_xxx"""
    m = FOLDER_RE.match(folder)
    return m.group(1) if m else folder


def find_accounts(root: str) -> list:
    """扫描 root 下的账号目录"""
    out = []
    if not root or not os.path.isdir(root):
        return out
    for folder in sorted(os.listdir(root)):
        db_dir = os.path.join(root, folder, 'db_storage')
        if not os.path.isdir(db_dir):
            continue
        db_count = size = 0
        last = 0
        for dirpath, _, names in os.walk(db_dir):
            for n in names:
                if n.endswith('.db'):
                    p = os.path.join(dirpath, n)
                    try:
                        st = os.stat(p)
                        db_count += 1
                        size += st.st_size
                        last = max(last, st.st_mtime)
                    except OSError:
                        pass
        out.append({
            'folder': folder,
            'username': account_username(folder),
            'base_dir': os.path.join(root, folder),
            'db_dir': db_dir,
            'db_count': db_count,
            'size_mb': round(size / 1024 / 1024, 1),
            'last_active': int(last),
        })
    out.sort(key=lambda a: -a['last_active'])
    return out


def find_kvcomm_codes() -> list:
    """图片密钥推导用的 code 集合（%APPDATA%/Tencent/xwechat/*/kvcomm/key_<code>_*.statistic）"""
    appdata = os.environ.get('APPDATA', '')
    if not appdata:
        return []
    pattern = os.path.join(appdata, 'Tencent', 'xwechat', '*', 'kvcomm', 'key_*_*.statistic')
    codes = set()
    for p in glob.glob(pattern):
        name = os.path.basename(p)
        m = re.match(r'key_(\d+)_', name)
        if m:
            codes.add(m.group(1))
    return sorted(codes)


def weixin_running() -> bool:
    try:
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Weixin.exe', '/FO', 'CSV', '/NH'],
                           capture_output=True, text=True, timeout=10)
        return 'Weixin.exe' in (r.stdout or '')
    except Exception:
        return False


def default_export_dir() -> str:
    home = Path(os.environ.get('USERPROFILE', 'C:/Users'))
    return str(home / 'Desktop' / '微信聊天记录导出')
