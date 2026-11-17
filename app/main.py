# -*- coding: utf-8 -*-
"""应用入口：本地 FastAPI + pywebview 原生窗口"""
import argparse
import json
import multiprocessing
import os
import secrets
import socket
import sys
import urllib.request
import threading
import time
import traceback
import webbrowser
from pathlib import Path

import uvicorn

from app.api.routes import create_app
from app.core import discovery, tools


def _base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def ensure_std_streams():
    """PyInstaller 窗口模式（console=False）下 sys.stdout/stderr 为 None。

    uvicorn 初始化日志时会调用 sys.stdout.isatty()，None 会抛异常；异常发生在
    后台线程里，外部表现为双击后没有窗口、约 20 秒后进程静默退出。
    这里用 devnull 兜底，保证无控制台时也能正常启动。
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')


def report_startup_error(text: str):
    """启动失败时写日志并弹窗提示，避免窗口模式下错误被吞掉。"""
    log_path = _base_dir() / '启动错误.log'
    try:
        log_path.write_text(text, encoding='utf-8')
    except OSError:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f'程序启动失败，详情已写入：\n{log_path}\n\n{text[-800:]}',
            '微信聊天记录导出',
            0x10,
        )
    except Exception:
        pass


def show_message(text: str):
    """轻量提示框（启动失败/重复启动）"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, text, '微信聊天记录导出', 0x40)
    except Exception:
        print(text, flush=True)


_MUTEX_HANDLE = None


def acquire_single_instance() -> bool:
    """Windows 命名互斥量：已有实例时返回 False"""
    global _MUTEX_HANDLE
    if os.name != 'nt':
        return True
    try:
        import ctypes
        handle = ctypes.windll.kernel32.CreateMutexW(
            None, False, 'Local\\WeChatExporter_SingleInstance')
        if not handle:
            return True
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            ctypes.windll.kernel32.CloseHandle(handle)
            return False
        _MUTEX_HANDLE = handle
        return True
    except Exception:
        return True


def runtime_url_file() -> Path:
    return _base_dir() / '.runtime_url'


def free_port() -> int:
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_server(port, token='', timeout=60) -> bool:
    """等待本程序服务就绪：不仅探测端口，还校验 /api/bootstrap 身份"""
    url = f'http://127.0.0.1:{port}/api/bootstrap'
    headers = {'X-Auth-Token': token} if token else {}
    end = time.time() + timeout
    while time.time() < end:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=1.5) as r:
                data = json.loads(r.read().decode('utf-8'))
            if isinstance(data, dict) and 'version' in data:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def main():
    ensure_std_streams()
    # 内置 FFmpeg/ffprobe：启动时前置到 PATH，子进程无需用户另行安装
    tools.ensure_tools_on_path()
    try:
        _run()
    except Exception:
        report_startup_error(traceback.format_exc())
        raise


def _run():
    multiprocessing.freeze_support()
    ap = argparse.ArgumentParser()
    ap.add_argument('--browser', action='store_true', help='用默认浏览器打开')
    ap.add_argument('--port', type=int, default=0)
    ap.add_argument('--token', default='', help='API 访问令牌（默认随机生成）')
    args = ap.parse_args()

    if not acquire_single_instance():
        existing = ''
        try:
            existing = runtime_url_file().read_text(encoding='utf-8').strip()
        except OSError:
            pass
        if existing:
            webbrowser.open(existing)
            show_message('程序已在运行，已尝试打开现有窗口。')
        else:
            show_message('程序已在运行。')
        return

    token = (args.token or os.environ.get('WECHAT_EXPORTER_TOKEN')
             or secrets.token_urlsafe(24))
    app = create_app(token=token)
    server_errors = []

    def serve(port):
        try:
            uvicorn.run(app, host='127.0.0.1', port=port,
                        log_level='warning', access_log=False)
        except Exception:
            server_errors.append(traceback.format_exc())

    ports = [args.port] if args.port else [free_port() for _ in range(3)]
    port = 0
    for candidate in ports:
        server_errors.clear()
        threading.Thread(target=serve, args=(candidate,), daemon=True).start()
        if wait_server(candidate, token, timeout=60):
            port = candidate
            break
        if server_errors and 'address already in use' not in server_errors[-1].lower():
            break
    if not port:
        detail = server_errors[-1] if server_errors else '（服务线程未在超时内就绪）'
        raise RuntimeError(f'本地服务启动失败\n{detail}')

    url = f'http://127.0.0.1:{port}/?token={token}'
    print(f'本地服务地址（含访问令牌）：{url}', flush=True)
    try:
        runtime_url_file().write_text(url, encoding='utf-8')
    except OSError:
        pass
    try:
        if args.browser:
            webbrowser.open(url)
            while True:
                time.sleep(3600)
        else:
            import webview
            webview.create_window(
                '微信聊天记录导出', url, width=1220, height=820,
                min_size=(980, 640), background_color='#f7f8fa')
            webview.start()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            runtime_url_file().unlink()
        except OSError:
            pass
        discovery.shutdown_everything()

if __name__ == '__main__':
    main()
