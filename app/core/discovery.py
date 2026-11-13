# -*- coding: utf-8 -*-
"""发现微信数据目录、账号、版本、图片密钥 code"""
import glob
import os
import re
from app.core import proc
import sys
from pathlib import Path

FOLDER_RE = re.compile(r'^(.+)_[0-9a-f]{4}$')
# 递归扫描时跳过的无关目录，避免扫描整盘时浪费时间
SKIP_DIR_NAMES = {
    '$recycle.bin', 'system volume information', 'node_modules', '.git',
    'windows', 'winsxs', 'program files', 'program files (x86)',
    'appdata', 'application data', 'temp', 'tmp',
}
# 深层递归时只进入名字与之相关的目录，避免选中整盘时全盘遍历
RECURSE_HINT = ('wechat', 'weixin', 'tencent', 'xwechat', '微信')
WECHAT_EXES = [
    r'C:\Program Files\Tencent\Weixin\Weixin.exe',
    r'C:\Program Files (x86)\Tencent\Weixin\Weixin.exe',
    r'C:\Program Files\Tencent\WeChat\WeChat.exe',
    r'C:\Program Files (x86)\Tencent\WeChat\WeChat.exe',
]


def candidate_roots():
    """常见的微信数据根目录（含各盘符根目录，兼容改过存储路径的情况）"""
    home = Path(os.environ.get('USERPROFILE', 'C:/Users'))
    out = [home / 'Documents' / 'xwechat_files']
    for drive in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
        if os.path.exists(f'{drive}:/'):
            out.append(Path(f'{drive}:/xwechat_files'))
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
                r = proc.run(
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


def _is_account_dir(path: str) -> bool:
    """账号目录的标志：直接包含 db_storage 子目录"""
    return os.path.isdir(os.path.join(path, 'db_storage'))


def _scan_account_dirs(root: str, max_depth: int = 3) -> list:
    """从 root 开始查找账号目录。

    先看 root 直下一层（标准结构），找不到再逐层向下递归，
    这样即使用户把微信存储路径改到别处、或选中的是更上层的父目录，
    只要选中范围内存在 `<xxx>/db_storage` 就能被发现。
    返回账号目录（含 db_storage 的那一层）的绝对路径列表。
    """
    root = os.path.abspath(root)
    found = []
    if _is_account_dir(root):
        return [root]

    # 标准结构：root 本身就是数据根目录
    try:
        children = sorted(os.listdir(root))
    except OSError:
        return found
    for name in children:
        path = os.path.join(root, name)
        if _is_account_dir(path):
            found.append(path)
    if found:
        return found

    # 兜底：在选定目录下按层递归查找（最多 max_depth 层）
    is_drive_root = len(root) <= 3 and root[1:2] == ':'
    queue = [(root, 0)]
    budget = 4000  # 目录访问上限，防止误选整盘时长时间扫描
    while queue and budget > 0:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        budget -= 1
        try:
            names = sorted(os.listdir(current))
        except OSError:
            continue
        for name in names:
            if name.startswith('$') or name.lower() in SKIP_DIR_NAMES:
                continue
            path = os.path.join(current, name)
            if not os.path.isdir(path) or os.path.islink(path):
                continue
            if _is_account_dir(path):
                found.append(path)
                continue  # 账号目录内部不再深入
            # 下层只进入与微信相关的目录（选中盘符根目录时第一层也做限制）
            if depth >= 1 or is_drive_root:
                lower = name.lower()
                if not any(k in lower for k in RECURSE_HINT):
                    continue
            queue.append((path, depth + 1))
    return found


def find_accounts(root: str, recursive: bool = True) -> list:
    """扫描 root 下的账号目录（默认递归查找）"""
    out = []
    if not root or not os.path.isdir(root):
        return out
    max_depth = 3 if recursive else 0
    seen = set()
    for base_dir in _scan_account_dirs(root, max_depth=max_depth):
        if base_dir in seen:
            continue
        seen.add(base_dir)
        folder = os.path.basename(base_dir.rstrip('\\/'))
        db_dir = os.path.join(base_dir, 'db_storage')
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
            'base_dir': base_dir,
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
        r = proc.run(['tasklist', '/FI', 'IMAGENAME eq Weixin.exe', '/FO', 'CSV', '/NH'],
                           capture_output=True, text=True, timeout=10)
        return 'Weixin.exe' in (r.stdout or '')
    except Exception:
        return False


def default_export_dir() -> str:
    home = Path(os.environ.get('USERPROFILE', 'C:/Users'))
    return str(home / 'Desktop' / '微信聊天记录导出')
