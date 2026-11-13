# -*- coding: utf-8 -*-
"""启动逻辑测试：单实例互斥、服务身份校验"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.media import ffmpeg_status  # noqa: E402
from app.main import acquire_single_instance, wait_server  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


class _Handler(BaseHTTPRequestHandler):
    body = b'{"version": "test"}'

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


def _serve(body):
    handler = type('H', (_Handler,), {'body': body})
    srv = HTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def main():
    if os.name == 'nt':
        assert acquire_single_instance() is True
        assert acquire_single_instance() is False, '第二个实例应被拒绝'
        print('  ok  单实例互斥')

    srv, port = _serve(b'{"version": "test"}')
    try:
        assert wait_server(port, 'token', timeout=3) is True
    finally:
        srv.shutdown()
    print('  ok  识别本程序服务')

    srv, port = _serve(b'{"hello": "other service"}')
    try:
        assert wait_server(port, 'token', timeout=1) is False, '其他服务不应被误认'
    finally:
        srv.shutdown()
    print('  ok  拒绝非本程序端口')

    st = ffmpeg_status('C:/definitely-missing/ffmpeg.exe')
    assert st['available'] is False, st
    print('  ok  FFmpeg 缺失检测')

    print('启动逻辑测试全部通过')


if __name__ == '__main__':
    main()
