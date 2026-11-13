# -*- coding: utf-8 -*-
"""应用入口：本地 FastAPI + pywebview 原生窗口"""
import argparse
import multiprocessing
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from app.api.routes import create_app


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
    multiprocessing.freeze_support()
    ap = argparse.ArgumentParser()
    ap.add_argument('--browser', action='store_true', help='用默认浏览器打开')
    ap.add_argument('--port', type=int, default=0)
    args = ap.parse_args()

    app = create_app()
    port = args.port or free_port()
    threading.Thread(
        target=lambda: uvicorn.run(app, host='127.0.0.1', port=port,
                                   log_level='warning', access_log=False),
        daemon=True).start()
    if not wait_server(port):
        print('本地服务启动失败')
        sys.exit(1)

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
