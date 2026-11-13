# -*- coding: utf-8 -*-
"""生成 README/文档使用的界面截图。

用法（在项目根目录）：
    python tools/capture_screenshots.py

脚本会：
1. 用本地 http.server 托管 webui/dist（需先 `npm run build`）
2. 用 Playwright 拦截全部 /api 请求，返回合成的演示数据
3. 截取四步向导、聊天预览、富消息详情、导出完成等界面（浅色 + 深色）
4. 输出到 docs/screenshots/*.png

所有演示数据均为虚构，不读取本机微信数据。
"""
from __future__ import annotations

import io
import json
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'webui' / 'dist'
OUT = ROOT / 'docs' / 'screenshots'
PORT = 8766
BASE = f'http://127.0.0.1:{PORT}'

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ACCOUNT = 'wxid_demo_primary'

BOOTSTRAP = {
    'version': '0.1.0',
    'wechat_root': r'C:\Users\Demo\Documents\xwechat_files',
    'detected_root': r'C:\Users\Demo\Documents\xwechat_files',
    'wechat_version': '4.2.0.13',
    'weixin_running': True,
    'export_dir': r'D:\WeChatExporter\exports',
    'last_account': ACCOUNT,
    'accounts': [
        {
            'folder': ACCOUNT,
            'username': ACCOUNT,
            'nickname': '林小满',
            'size_mb': 212.4,
            'db_count': 20,
            'last_active': 1762992000,
            'has_keys': True,
            'decrypted': True,
            'images_decoded': 1832,
            'voices_decoded': 96,
            'videos_indexed': 18,
        },
        {
            'folder': 'wxid_demo_second',
            'username': 'wxid_demo_second',
            'nickname': '演示小号',
            'size_mb': 18.7,
            'db_count': 22,
            'last_active': 1761955200,
            'has_keys': False,
            'decrypted': False,
            'images_decoded': 0,
            'voices_decoded': 0,
            'videos_indexed': 0,
        },
    ],
}

SESSIONS = [
    {'username': 'demo_product', 'name': '产品设计讨论组', 'summary': '下周的版本计划我看过了，整体节奏没问题', 'is_group': True, 'count': 1286, 'last_time_text': '2026-11-13 09:28'},
    {'username': 'demo_readers', 'name': '读书会 · 周末共读', 'summary': '本周共读《置身事内》第三章，记得打卡', 'is_group': True, 'count': 864, 'last_time_text': '2026-11-12 20:01'},
    {'username': 'demo_project_a', 'name': '项目 A 交付群', 'summary': '联调环境已恢复，可以继续验证了', 'is_group': True, 'count': 612, 'last_time_text': '2026-11-12 16:42'},
    {'username': 'demo_lin', 'name': '小林', 'summary': '好的，明早我把整理好的文档发你', 'is_group': False, 'count': 498, 'last_time_text': '2026-11-12 11:07'},
    {'username': 'demo_frontend', 'name': '前端技术交流群', 'summary': '这个动画用 View Transitions 实现会更顺', 'is_group': True, 'count': 437, 'last_time_text': '2026-11-11 22:15'},
    {'username': 'demo_family', 'name': '家庭群', 'summary': '周末回家吃饭吗？', 'is_group': True, 'count': 296, 'last_time_text': '2026-11-11 18:30'},
    {'username': 'demo_design', 'name': '视觉设计小组', 'summary': '新的图标集已经上传到共享盘', 'is_group': True, 'count': 188, 'last_time_text': '2026-11-10 14:22'},
    {'username': 'demo_photo', 'name': '摄影爱好者', 'summary': '周三日出机位有人一起吗', 'is_group': True, 'count': 152, 'last_time_text': '2026-11-09 21:04'},
]

MESSAGES = [
    {'local_id': 1, 'sender': '系统', 'time': '2026-11-12 16:40', 'text': '你邀请 林小满、陈一 加入了群聊', 'kind': 'system'},
    {'local_id': 2, 'sender': '陈一', 'time': '2026-11-12 16:42', 'text': '联调环境已经恢复，大家可以继续验证了', 'kind': 'text'},
    {'local_id': 3, 'sender': '我', 'time': '2026-11-12 16:44', 'text': '收到，我先把导出链路的用例跑一遍', 'kind': 'text'},
    {
        'local_id': 4,
        'sender': '陈一',
        'time': '2026-11-12 16:45',
        'text': '引用消息',
        'kind': 'quote',
        'content': {'quote': {'sender': '我', 'text': '收到，我先把导出链路的用例跑一遍'}, 'reply': '好，重点看下大群（>5 万条）的导出耗时'},
    },
    {
        'local_id': 5,
        'sender': '我',
        'time': '2026-11-12 16:48',
        'text': '',
        'kind': 'link',
        'content': {'title': 'SQLCipher 4 页级解密的性能实践', 'des': '逐页解密、增量跳过与并发策略的工程记录。', 'url': 'https://example.com/blog/sqlcipher-benchmark'},
    },
    {
        'local_id': 6,
        'sender': '陈一',
        'time': '2026-11-12 16:50',
        'text': '',
        'kind': 'file',
        'content': {'title': '导出验收清单_20261112.pdf', 'size': '1.2 MB'},
    },
    {
        'local_id': 7,
        'sender': '陈一',
        'time': '2026-11-12 16:52',
        'text': '[图片]',
        'kind': 'image',
        'media': r'D:\WeChatExporter\demo\mock-photo.png',
    },
    {
        'local_id': 8,
        'sender': '我',
        'time': '2026-11-12 16:54',
        'text': '转账 ¥ 200.00',
        'kind': 'transfer',
        'content': {'title': '转账 ¥ 200.00', 'des': '请查收，辛苦了'},
    },
    {
        'local_id': 9,
        'sender': '陈一',
        'time': '2026-11-12 16:56',
        'text': '聊天记录',
        'kind': 'chat_history',
        'content': {
            'title': '陈一和你的聊天记录',
            'des': '共 3 条',
            'records': [
                {'sender': '陈一', 'time': '11-12 09:12', 'text': '数据库解密的增量逻辑我补了测试', 'kind': 'text'},
                {'sender': '我', 'time': '11-12 09:15', 'text': '好，顺便看下异常数据库的跳过策略', 'kind': 'text'},
                {'sender': '陈一', 'time': '11-12 09:21', 'text': '已处理，失败库会在日志里单独列出', 'kind': 'text'},
            ],
        },
    },
    {'local_id': 10, 'sender': '我', 'time': '2026-11-12 17:02', 'text': '那今天先到这里，明早同步进度', 'kind': 'text'},
]

JOB_POLLS = {'n': 0}


def mock_png() -> bytes:
    img = Image.new('RGB', (640, 400))
    d = ImageDraw.Draw(img)
    for y in range(400):
        t = y / 399
        r = int(232 + (147 - 232) * t)
        g = int(247 + (197 - 247) * t)
        b = int(238 + (253 - 238) * t)
        d.line([(0, y), (640, y)], fill=(r, g, b))
    d.rounded_rectangle((40, 40, 600, 360), radius=18, fill=(255, 255, 255), outline=(180, 230, 200), width=2)
    d.ellipse((80, 90, 240, 250), fill=(7, 193, 96))
    d.rounded_rectangle((280, 110, 560, 150), radius=10, fill=(225, 245, 232))
    d.rounded_rectangle((280, 170, 520, 210), radius=10, fill=(235, 240, 245))
    d.rounded_rectangle((280, 230, 480, 270), radius=10, fill=(235, 240, 245))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


PHOTO = mock_png()


def json_response(route, data):
    route.fulfill(status=200, content_type='application/json',
                  body=json.dumps(data, ensure_ascii=False))


def handle_api(route, request):
    url = request.url
    path = url.split('?', 1)[0]
    if path.endswith('/api/bootstrap'):
        return json_response(route, BOOTSTRAP)
    if path.endswith('/api/sessions'):
        return json_response(route, {'sessions': SESSIONS})
    if path.endswith('/api/chat'):
        return json_response(route, {'messages': MESSAGES})
    if path.endswith('/api/export'):
        JOB_POLLS['n'] = 0
        return json_response(route, {'job': 'demo-export'})
    if '/api/jobs/' in path:
        JOB_POLLS['n'] += 1
        if JOB_POLLS['n'] < 6:
            pct = min(95, JOB_POLLS['n'] * 18)
            return json_response(route, {'status': 'running', 'progress': pct,
                                         'message': f'正在导出第 {min(JOB_POLLS["n"], 2)}/2 个会话…',
                                         'logs': ['解析会话：产品设计讨论组', '解析会话：读书会 · 周末共读']})
        return json_response(route, {
            'status': 'done', 'progress': 100, 'message': '已生成 4 个文件',
            'logs': [],
            'result': {
                'dir': r'D:\WeChatExporter\exports\导出_20261113_1200',
                'files': [
                    r'D:\WeChatExporter\exports\导出_20261113_1200\产品设计讨论组\index.html',
                    r'D:\WeChatExporter\exports\导出_20261113_1200\产品设计讨论组\聊天记录.txt',
                    r'D:\WeChatExporter\exports\导出_20261113_1200\读书会 · 周末共读\index.html',
                    r'D:\WeChatExporter\exports\导出_20261113_1200\读书会 · 周末共读\聊天记录.txt',
                ],
            },
        })
    if path.endswith('/api/file'):
        route.fulfill(status=200, content_type='image/png', body=PHOTO)
        return
    if path.endswith('/api/config') or path.endswith('/api/open-folder'):
        return json_response(route, {'ok': True})
    return json_response(route, {'ok': True})


def serve_dist():
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(DIST), **kw)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def scroll_main(page, pos: str = 'top'):
    """页面滚动发生在 .main 容器内，截图前统一回到顶部/底部。"""
    page.evaluate(
        "(pos) => { const m = document.querySelector('.main');"
        " if (m) m.scrollTop = pos === 'bottom' ? m.scrollHeight : 0 }",
        pos,
    )
    page.wait_for_timeout(250)


def shot(page, name: str, full: bool = False):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    page.screenshot(path=str(path), full_page=full)
    img = Image.open(path)
    img.save(path, optimize=True)
    print(f'  ✓ {path.relative_to(ROOT)}  {path.stat().st_size / 1024:.0f} KB')


def main():
    if not DIST.exists():
        raise SystemExit('webui/dist 不存在，请先在 webui 目录执行 npm run build')
    httpd = serve_dist()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={'width': 1280, 'height': 800},
                                  device_scale_factor=2, locale='zh-CN')
        page = ctx.new_page()
        page.route('**/api/**', handle_api)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))

        print('生成截图：')
        page.goto(BASE, wait_until='networkidle')
        page.get_by_text('选择要导出的微信账号').wait_for()
        scroll_main(page)
        shot(page, '01-accounts-light.png')

        page.get_by_role('button', name='下一步').click()
        page.get_by_text('准备数据', exact=True).first.wait_for()
        page.wait_for_timeout(300)
        scroll_main(page)
        shot(page, '02-prepare-light.png')

        page.get_by_role('button', name='下一步').click()
        page.get_by_text('产品设计讨论组').wait_for()
        page.wait_for_timeout(300)
        scroll_main(page)
        shot(page, '03-sessions-light.png')

        # 聊天预览（浅色）
        scroll_main(page)
        page.get_by_text('产品设计讨论组').click()
        page.locator('.chat-view').wait_for()
        page.wait_for_timeout(600)
        shot(page, '04-chat-preview-light.png')

        # 转发聊天记录详情
        page.locator('.card.clickable').first.click()
        page.locator('.record-view').wait_for()
        page.wait_for_timeout(300)
        shot(page, '05-record-detail-light.png')
        page.locator('.record-view').press('Escape')
        page.keyboard.press('Escape')
        page.wait_for_timeout(400)
        page.keyboard.press('Escape')
        page.wait_for_timeout(400)

        # 勾选两个会话 → 导出页
        boxes = page.locator('.sess .n-checkbox')
        boxes.nth(0).click()
        boxes.nth(1).click()
        page.get_by_role('button', name='下一步').click()
        page.get_by_text('导出格式').wait_for()
        page.wait_for_timeout(300)
        scroll_main(page)
        shot(page, '06-export-light.png')

        # 导出进行中 → 完成
        page.get_by_role('button', name='开始导出').click()
        page.get_by_text('正在导出').wait_for()
        page.wait_for_timeout(700)
        scroll_main(page, 'bottom')
        shot(page, '07-export-progress-light.png')
        page.get_by_text('导出完成').wait_for(timeout=15000)
        page.wait_for_timeout(300)
        page.set_viewport_size({'width': 1280, 'height': 1100})
        scroll_main(page)
        shot(page, '08-export-done-light.png')

        # 深色模式：导出页、会话页、聊天预览
        page.locator('header .n-switch').click()
        page.wait_for_timeout(400)
        scroll_main(page)
        shot(page, '09-export-done-dark.png')

        page.set_viewport_size({'width': 1280, 'height': 800})
        page.get_by_text('选择会话', exact=True).first.click()
        page.wait_for_timeout(500)
        scroll_main(page)
        shot(page, '10-sessions-dark.png')

        scroll_main(page)
        page.get_by_text('产品设计讨论组').click()
        page.locator('.chat-view').wait_for()
        page.wait_for_timeout(600)
        shot(page, '11-chat-preview-dark.png')

        if errors:
            print('前端脚本错误：')
            for e in errors:
                print('  ✗', e)
        browser.close()
    httpd.shutdown()
    print('完成。')


if __name__ == '__main__':
    main()
