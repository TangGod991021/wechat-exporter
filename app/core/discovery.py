# -*- coding: utf-8 -*-
"""发现微信数据目录、账号、版本、图片密钥 code"""
import glob
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
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


def _documents_dirs() -> list:
    """Documents 目录候选：本地、OneDrive 重定向与注册表实际路径"""
    home = Path(os.environ.get('USERPROFILE', 'C:/Users'))
    dirs = [home / 'Documents']
    for env in ('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial'):
        base = os.environ.get(env)
        if base:
            dirs.append(Path(base) / 'Documents')
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Explorer'
                r'\User Shell Folders') as key:
            value, _ = winreg.QueryValueEx(key, 'Personal')
        dirs.append(Path(os.path.expandvars(value)))
    except Exception:
        pass
    out = []
    for d in dirs:
        key = str(d).lower()
        if key not in {str(x).lower() for x in out}:
            out.append(d)
    return out


def candidate_roots():
    """常见的微信数据根目录（含盘符根与 OneDrive 重定向文档）"""
    out = [d / 'xwechat_files' for d in _documents_dirs()]
    for drive in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
        if os.path.exists(f'{drive}:/'):
            out.append(Path(f'{drive}:/xwechat_files'))
    return [str(p) for p in out]


def detect_wechat_root() -> str:
    for root in candidate_roots():
        if not os.path.isdir(root):
            continue
        try:
            accounts = [d for d in os.listdir(root)
                        if os.path.isdir(os.path.join(root, d, 'db_storage'))]
        except OSError:
            continue
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


# ---------- Everything 集成：快速定位 xwechat_files ----------

EVERYTHING_PORTS = [80, 8080]
# 便携版默认配置：静默运行，不提权、不进任务栏，只保留托盘图标
EVERYTHING_INI = ('run_as_admin=0\n'
                  'show_in_taskbar=0\n'
                  'minimize_to_tray=1\n'
                  'show_tray_icon=1\n')
_started_everything = ''   # 本程序拉起的 Everything.exe 路径
_started_proc = None       # 对应的 Popen，用于确认进程仍存活


def _app_base_dirs() -> list:
    """程序目录候选：源码运行 / 打包后 exe 同级 / PyInstaller 解包目录"""
    dirs = []
    if getattr(sys, 'frozen', False):
        dirs.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            dirs.append(Path(meipass))
    else:
        dirs.append(Path(__file__).resolve().parent.parent.parent)
    return dirs


def _bundled_dirs() -> list:
    """随程序分发的 Everything 目录（everything/ 或 packaging/everything/）"""
    out = []
    for base in _app_base_dirs():
        out += [base / 'everything', base / 'packaging' / 'everything',
                base / '_internal' / 'everything', base / 'tools']
    return out


def find_es_exe() -> str:
    """查找 Everything 命令行工具 es.exe（环境变量 / PATH / 安装目录 / 随程序分发）"""
    env = os.environ.get('WECHAT_EXPORTER_ES', '')
    if env and os.path.isfile(env):
        return env
    found = shutil.which('es.exe') or shutil.which('es')
    if found:
        return found
    for folder in _bundled_dirs():
        p = folder / 'es.exe'
        try:
            if p.is_file():
                return str(p)
        except OSError:
            pass
    for folder in (Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Everything',
                   Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Everything',
                   Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Everything'):
        p = folder / 'es.exe'
        try:
            if p.is_file():
                return str(p)
        except OSError:
            pass
    return ''


def find_everything_exe(es_exe: str = '') -> str:
    """查找 Everything.exe：优先与 es.exe 同目录，其次随程序分发的目录"""
    candidates = []
    if es_exe:
        candidates.append(Path(es_exe).resolve().parent / 'everything.exe')
    for folder in _bundled_dirs():
        candidates.append(folder / 'everything.exe')
    candidates += [
        Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Everything' / 'Everything.exe',
        Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Everything' / 'Everything.exe',
        Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Everything' / 'Everything.exe',
    ]
    for p in candidates:
        try:
            if p.is_file():
                return str(p)
        except OSError:
            pass
    return ''


def everything_status() -> dict:
    es = find_es_exe()
    return {'available': bool(es), 'es_path': es,
            'exe_path': find_everything_exe(es) if es else ''}


def _es_ping(es_exe: str) -> bool:
    """es.exe 能连上本程序的 Everything 实例时返回 True"""
    try:
        r = proc.run([es_exe, '-n', '1', '__wechat_exporter_ping__'],
                     capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def _hide_process_windows(pid: int):
    """隐藏指定进程的顶层窗口（静默启动 Everything，不弹窗）"""
    if os.name != 'nt':
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _lparam):
            wpid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid:
                user32.ShowWindow(hwnd, 0)  # SW_HIDE
            return True

        user32.EnumWindows(enum_proc(callback), 0)
    except Exception:
        pass


def _hide_windows_for(pid: int, seconds: float = 10.0):
    """启动初期持续隐藏窗口，避免 Everything 首帧闪现

    前 3 秒高频轮询（50ms），之后降低频率，兼顾静默与 CPU 占用。
    """
    start = time.time()
    deadline = start + seconds
    while True:
        _hide_process_windows(pid)
        now = time.time()
        if now >= deadline:
            break
        time.sleep(0.05 if now - start < 3 else 0.2)


def ensure_everything_running(wait: float = 15.0) -> bool:
    """确保本程序的 Everything 独立实例在运行；未运行时自动拉起便携版。"""
    global _started_everything, _started_proc
    es_exe = find_es_exe()
    if not es_exe:
        return False
    if _es_ping(es_exe):
        return True
    exe = find_everything_exe(es_exe)
    if not exe:
        return False
    # 便携配置：默认不提权、不进任务栏
    ini = Path(exe).with_name('Everything.ini')
    try:
        if not ini.exists():
            ini.write_text(EVERYTHING_INI, encoding='utf-8')
    except OSError:
        pass
    try:
        p = proc.spawn([exe, '-minimized'])
        threading.Thread(target=_hide_windows_for, args=(p.pid, 10.0),
                         daemon=True).start()
    except Exception:
        return False
    deadline = time.time() + wait
    while time.time() < deadline:
        if p.poll() is not None:
            return False  # 启动后立即退出（被已有实例接管或配置异常）
        if _es_ping(es_exe):
            # 确认进程仍存活后才登记，避免退出时误关其他实例
            _started_everything = exe
            _started_proc = p
            return True
        time.sleep(0.5)
    return False


def shutdown_everything():
    """只关闭本程序拉起且仍存活的 Everything 进程（按 PID，不影响用户实例）"""
    global _started_everything, _started_proc
    _started_everything = ''
    p = _started_proc
    _started_proc = None
    if p is None or p.poll() is not None:
        return
    try:
        # 不带 /F 是发送 WM_CLOSE，让 Everything 正常保存索引
        proc.run(['taskkill', '/PID', str(p.pid)],
                 capture_output=True, timeout=8)
        p.wait(timeout=5)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def _decode_output(raw) -> str:
    if not raw:
        return ''
    if isinstance(raw, str):
        return raw
    for enc in ('utf-8', 'gbk', 'mbcs'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', 'replace')


def _es_search(query: str, limit: int = 200, es_exe: str = '') -> list:
    """调用 es.exe 搜索，返回完整路径列表。Everything 未运行或无结果时返回空。"""
    exe = es_exe or find_es_exe()
    if not exe:
        return []
    try:
        r = proc.run([exe, '-n', str(limit), query],
                     capture_output=True, timeout=20)
    except Exception:
        return []
    text = _decode_output(getattr(r, 'stdout', b''))
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _everything_http_search(query: str, limit: int = 200) -> list:
    """Everything 内置 HTTP 服务器的 JSON 接口（需用户在 Everything 中开启）"""
    ports = []
    env = os.environ.get('WECHAT_EXPORTER_EVERYTHING_PORT', '')
    if env.isdigit():
        ports.append(int(env))
    ports += [p for p in EVERYTHING_PORTS if p not in ports]
    for port in ports:
        url = ('http://127.0.0.1:%d/?search=%s&json=1&count=%d&path_column=1'
               % (port, urllib.parse.quote(query), limit))
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                data = json.loads(r.read().decode('utf-8', 'replace'))
        except Exception:
            continue
        out = []
        for item in data.get('results', []) or []:
            name = (item.get('name') or '').strip()
            path = (item.get('path') or '').strip()
            if name:
                out.append(os.path.join(path, name) if path else name)
        if out:
            return out
    return []


def _wechat_roots_from_paths(paths) -> list:
    """把 Everything 返回的 db_storage / xwechat_files / 账号目录转换为数据根目录"""
    roots = {}
    for raw in paths:
        p = os.path.normpath(str(raw).strip().strip('"'))
        if not p or not os.path.isdir(p):
            continue
        name = os.path.basename(p).lower()
        if name == 'xwechat_files':
            roots.setdefault(p.lower(), p)
            continue
        if name == 'db_storage':
            account = os.path.dirname(p)
        elif FOLDER_RE.match(os.path.basename(p)) and _is_account_dir(p):
            account = p
        else:
            continue
        root = os.path.dirname(account)
        if not root:
            continue
        # 降低误判：账号目录应符合 wxid_xxx_abcd，或数据根名为 xwechat_files
        account_name = os.path.basename(account)
        if not FOLDER_RE.match(account_name) and \
                os.path.basename(root).lower() != 'xwechat_files':
            continue
        roots.setdefault(root.lower(), root)
    return list(roots.values())


def _fallback_roots() -> list:
    """Everything 不可用时的本地兜底：常见目录 + 各盘符下与微信相关的目录"""
    roots = []
    seen = set()

    def add(path):
        if path and os.path.isdir(path) and path.lower() not in seen:
            seen.add(path.lower())
            roots.append(path)

    for r in candidate_roots():
        add(r)
    for drive in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
        base = f'{drive}:/'
        if not os.path.exists(base):
            continue
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for name in names:
            lower = name.lower()
            if not any(k in lower for k in RECURSE_HINT + ('我的文档', 'documents')):
                continue
            path = os.path.join(base, name)
            if not os.path.isdir(path):
                continue
            add(os.path.join(path, 'xwechat_files'))
            add(path)
    return roots


def locate_wechat_roots() -> dict:
    """定位微信数据目录：优先 Everything（未运行则自动拉起），其次本地扫描。

    返回 {'source', 'everything_available', 'es_exe', 'roots': [{'path','accounts'}]}
    """
    es_exe = find_es_exe()
    paths = []
    source = ''
    if es_exe and ensure_everything_running():
        # 首次启动时索引可能还在建立，最多等待约 10 秒
        for _ in range(4):
            paths = _es_search('db_storage', es_exe=es_exe)
            paths += _es_search('xwechat_files', es_exe=es_exe)
            if paths:
                source = 'everything'
                break
            time.sleep(2.5)
    if not paths:
        paths = _everything_http_search('db_storage')
        paths += _everything_http_search('xwechat_files')
        if paths:
            source = 'everything'
    roots = _wechat_roots_from_paths(paths)
    if not roots:
        roots = _fallback_roots()
        source = source or 'scan'

    result = []
    for root in roots:
        accounts = find_accounts(root)
        if accounts:
            result.append({'path': root, 'accounts': accounts})
    result.sort(key=lambda r: (-len(r['accounts']),
                               -max(a['last_active'] for a in r['accounts'])))
    return {
        'source': source,
        'everything_available': bool(es_exe),
        'es_exe': es_exe,
        'roots': _dedupe_root_entries(result),
    }


def _dedupe_root_entries(entries: list) -> list:
    """父子目录可能扫到同一批账号，按 base_dir 去重，避免重复展示/扫描"""
    seen_accounts = set()
    unique = []
    for entry in entries:
        fresh = [a for a in entry['accounts']
                 if a['base_dir'] not in seen_accounts]
        if not fresh:
            continue
        seen_accounts.update(a['base_dir'] for a in fresh)
        unique.append({'path': entry['path'], 'accounts': fresh})
    return unique


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
