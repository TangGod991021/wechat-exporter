# -*- coding: utf-8 -*-
"""接口安全测试：令牌鉴权、Host 校验、路径白名单、链接 scheme 过滤"""
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient  # noqa: E402

from app.api.routes import create_app  # noqa: E402
from app.core.export import _safe_href  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TOKEN = 'test-token-123'


def make_client(base_url='http://127.0.0.1'):
    app = create_app(token=TOKEN)
    return app, TestClient(app, base_url=base_url)


def main():
    app, client = make_client()

    # 1. 无令牌 / 错误令牌被拒绝
    r = client.get('/api/bootstrap')
    assert r.status_code == 401, r.status_code
    r = client.get('/api/bootstrap', headers={'X-Auth-Token': 'bad'})
    assert r.status_code == 401, r.status_code
    r = client.get('/api/bootstrap', headers={'X-Auth-Token': TOKEN})
    assert r.status_code == 200, r.text
    r = client.get('/api/bootstrap', params={'token': TOKEN})
    assert r.status_code == 200, '查询参数令牌应被接受'
    print('  ok  令牌鉴权')

    # 2. 非本机 Host 被拒绝（防 DNS rebinding）
    _, evil = make_client(base_url='http://evil.example')
    r = evil.get('/api/bootstrap', headers={'X-Auth-Token': TOKEN})
    assert r.status_code == 403, r.status_code
    print('  ok  Host 校验')

    # 3. /api/file 只允许媒体与导出目录，且按目录边界判断
    with tempfile.TemporaryDirectory() as tmp:
        media = os.path.join(tmp, 'media')
        exports = os.path.join(tmp, 'exports')
        backup = os.path.join(tmp, 'media_backup')
        data = os.path.join(tmp, 'data')
        for d in (media, exports, backup, data):
            os.makedirs(d)
        inside = os.path.join(media, 'a.jpg')
        sibling = os.path.join(backup, 'secret.jpg')
        db_file = os.path.join(data, 'keys.json')
        for p in (inside, sibling, db_file):
            with open(p, 'w', encoding='utf-8') as f:
                f.write('x')
        app.state.cfg.update({
            'media_dir': media, 'export_dir': exports, 'data_dir': data,
            'wechat_root': tmp,
        })
        r = client.get('/api/file', params={'path': inside, 'token': TOKEN})
        assert r.status_code == 200, r.text
        r = client.get('/api/file', params={'path': sibling, 'token': TOKEN})
        assert r.status_code == 403, '前缀相同的兄弟目录不应放行'
        r = client.get('/api/file', params={'path': db_file, 'token': TOKEN})
        assert r.status_code == 403, 'data_dir 不应可读'
        r = client.get('/api/file', params={'path': inside})
        assert r.status_code == 401, '直链也必须带令牌'
    print('  ok  /api/file 路径白名单')

    # 4. open-path 只允许白名单目录
    with tempfile.TemporaryDirectory() as tmp:
        exports = os.path.join(tmp, 'exports')
        os.makedirs(exports)
        app.state.cfg.update({'export_dir': exports,
                              'media_dir': os.path.join(tmp, 'media')})
        with mock.patch('app.api.routes.os.startfile') as start:
            r = client.post('/api/open-path', json={'path': 'C:\\Windows\\System32\\calc.exe'},
                            headers={'X-Auth-Token': TOKEN})
            assert r.status_code == 403, r.status_code
            start.assert_not_called()
            r = client.post('/api/open-path', json={'path': exports},
                            headers={'X-Auth-Token': TOKEN})
            assert r.status_code == 200, r.text
            start.assert_called_once_with(exports)
    print('  ok  open-path 白名单')

    # 5. 链接 scheme 只允许 http/https/mailto
    assert _safe_href('https://example.com/a') == 'https://example.com/a'
    assert _safe_href('mailto:a@b.com') == 'mailto:a@b.com'
    for bad in ('javascript:alert(1)', 'data:text/html,<script>x</script>',
                'vbscript:msgbox(1)', 'file:///C:/Windows', ''):
        assert _safe_href(bad) == '', bad
    print('  ok  链接 scheme 过滤')

    # 6. 参数校验：非法 limit / 格式 / 日期在进入任务前返回 400
    h = {'X-Auth-Token': TOKEN}
    r = client.get('/api/chat', params={'account': 'x', 'username': 'y', 'limit': 0},
                   headers=h)
    assert r.status_code == 400, r.status_code
    r = client.post('/api/export',
                    json={'account': 'x', 'targets': ['a'], 'formats': ['pdf']},
                    headers=h)
    assert r.status_code == 400, r.status_code
    r = client.post('/api/export',
                    json={'account': 'x', 'targets': ['a'], 'formats': ['html'],
                          'since': '2024/1/1'}, headers=h)
    assert r.status_code == 400, r.status_code
    r = client.post('/api/export',
                    json={'account': 'x', 'targets': ['a'], 'formats': ['html'],
                          'since': '2024-02-01', 'until': '2024-01-01'}, headers=h)
    assert r.status_code == 400, r.status_code
    print('  ok  导出/预览参数校验')

    print('API 安全测试全部通过')


if __name__ == '__main__':
    main()
