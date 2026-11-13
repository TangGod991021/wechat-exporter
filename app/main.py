# -*- coding: utf-8 -*-
"""应用入口：本地 FastAPI + pywebview 原生窗口"""
import argparse
import multiprocessing
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

import uvicorn

from app.api.routes import create_app


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


def free_port() -> int:
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_server(port, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main():
    ensure_std_streams()
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
    args = ap.parse_args()

    app = create_app()
    port = args.port or free_port()
    server_errors = []

    def serve():
        try:
            uvicorn.run(app, host='127.0.0.1', port=port,
                        log_level='warning', access_log=False)
        except Exception:
            server_errors.append(traceback.format_exc())

    threading.Thread(target=serve, daemon=True).start()
    if not wait_server(port):
        detail = server_errors[0] if server_errors else '（服务线程未报告具体错误）'
        raise RuntimeError(f'本地服务启动失败\n{detail}')

    url = f'http://127.0.0.1:{port}'
    if args.browser:
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    import webview
    webview.create_window(
        '微信聊天记录导出', url, width=1220, height=820,
        min_size=(980, 640), background_color='#f7f8fa')
    webview.start()


if __name__ == '__main__':
    main()
