# -*- coding: utf-8 -*-
"""端到端冒烟测试：bootstrap -> keys -> decrypt -> sessions

先以固定令牌启动服务，再运行本脚本：
    set WECHAT_EXPORTER_TOKEN=devtoken
    python run.py --browser --token devtoken
    python tests/smoke.py
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = 'http://127.0.0.1:8765'
TOKEN = os.environ.get('WECHAT_EXPORTER_TOKEN', '')
HEADERS = {'X-Auth-Token': TOKEN} if TOKEN else {}


def get(path):
    req = urllib.request.Request(BASE + path, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json', **HEADERS}, method='POST')
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def wait(jid, timeout=600):
    t0 = time.time()
    last = -1
    while time.time() - t0 < timeout:
        j = get('/api/jobs/' + jid)
        if j['progress'] != last:
            print(f"  [{j['status']}] {j['progress']}% {j['message']}")
            last = j['progress']
        if j['status'] in ('done', 'error'):
            return j
        time.sleep(0.5)
    raise TimeoutError('job timeout')


boot = get('/api/bootstrap')
acc = boot['accounts'][0]
print('账号:', acc['nickname'], acc['username'])

print('== 提取密钥 ==')
j = wait(post('/api/keys', {'account': acc['folder']})['job'])
print('  result:', json.dumps(j['result'], ensure_ascii=False)[:300])
assert j['status'] == 'done', j['error']

print('== 解密数据库 ==')
j = wait(post('/api/decrypt', {'account': acc['folder']})['job'])
r = j['result']
print(f"  成功 {r['ok']} / 跳过 {r['skipped']} / 失败 {r['failed']}")
assert j['status'] == 'done' and r['failed'] == 0

print('== 会话列表 ==')
s = get('/api/sessions?account=' + acc['folder'])['sessions']
print('  会话数:', len(s))
for x in s[:5]:
    print(f"  {x['count']:>6} 条 | {x['name']} | {x['username']}")

print('== 聊天预览 ==')
target = next(x for x in s if x['count'] > 0)
msgs = get(f"/api/chat?account={acc['folder']}&username={urllib.parse.quote(target['username'])}&limit=5")['messages']
for m in msgs:
    print('  ', m['time'], m['sender'], ':', m['text'][:40])
print('SMOKE OK')
