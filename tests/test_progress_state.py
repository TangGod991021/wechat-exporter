# -*- coding: utf-8 -*-
"""进度上报与准备状态的离线测试（合成数据库，不读取真实微信数据）。"""
import hashlib
import hmac as hmac_mod
import json
import os
import sqlite3
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Crypto.Cipher import AES  # noqa: E402

from app.api.routes import account_state  # noqa: E402
from app.core.decrypt import (PAGE_SZ, RESERVE_SZ, SALT_SZ, derive_mac_key,  # noqa: E402
                              decrypt_all)
from app.core.export import ChatStore  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def _make_encrypted_db(path, key, pages):
    """按 SQLCipher 4 页面布局生成可被 decrypt_database 接受的合成库。"""
    salt = os.urandom(SALT_SZ)
    mac_key = derive_mac_key(key, salt)
    body_size = PAGE_SZ - RESERVE_SZ - SALT_SZ
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        for pgno in range(1, pages + 1):
            plain = (b'SQLite format 3\x00' if pgno == 1 else b'') + \
                    os.urandom(body_size - (16 if pgno == 1 else 0))
            plain = plain[:body_size].ljust(body_size, b'\x00')
            iv = os.urandom(16)
            enc = AES.new(key, AES.MODE_CBC, iv).encrypt(plain)
            page = bytearray(salt + enc + iv + b'\x00' * (RESERVE_SZ - 16))
            page = bytearray(page[:PAGE_SZ])
            if pgno == 1:
                h = hmac_mod.new(mac_key, bytes(page[SALT_SZ:PAGE_SZ - RESERVE_SZ + 16]) +
                                 struct.pack('<I', 1), hashlib.sha512)
                page[PAGE_SZ - 64:] = h.digest()
            f.write(bytes(page))


def test_decrypt_reports_paged_progress():
    key = os.urandom(32)
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'src')
        out = os.path.join(td, 'out')
        rels = {'a.db': 400, 'b.db': 1400}
        keys = {}
        for rel, pages in rels.items():
            _make_encrypted_db(os.path.join(src, rel), key, pages)
            keys[rel] = {'enc_key': key.hex(), 'salt': ''}
        events = []
        res = decrypt_all(src, out, keys,
                          progress=lambda p, m='': events.append((p, m)))
        assert res['ok'] == 2, res
        assert len(events) >= 8, f'进度回调太少：{events}'
        assert events[-1][0] == 100, events[-1]
        assert any('正在解密' in m for _p, m in events), events[:5]
        # 大库在单个库内部也应产生多次进度（每 512 页一次）
        big = [(p, m) for p, m in events if 'b.db' in m]
        assert len(big) >= 3, big
    print('OK: 解密按库大小加权并按页上报进度')


def test_account_state_restores_prepared_targets():
    with tempfile.TemporaryDirectory() as td:
        folder = 'wxid_demo_1234'
        cfg = {'data_dir': os.path.join(td, 'data'),
               'media_dir': os.path.join(td, 'media')}
        data_dir = os.path.join(cfg['data_dir'], folder)
        os.makedirs(data_dir)
        (open(os.path.join(data_dir, 'keys.json'), 'w', encoding='utf-8')).write('{}')
        (open(os.path.join(data_dir, 'prepared.json'), 'w', encoding='utf-8')).write(
            json.dumps({'targets': ['a@chatroom', 'wxid_b']}))
        account = {'folder': folder, 'username': 'wxid_demo',
                   'base_dir': os.path.join(td, 'base'), 'size_mb': 0,
                   'db_count': 0, 'last_active': 0, 'db_dir': os.path.join(td, 'db')}
        state = account_state(cfg, account)
        assert state['prepared_targets'] == ['a@chatroom', 'wxid_b'], state
        assert state['has_keys'] is True
    print('OK: 已准备会话可从 prepared.json 恢复')


def test_session_counts_are_cached():
    with tempfile.TemporaryDirectory() as td:
        user = 'demo_user'
        os.makedirs(os.path.join(td, 'session'))
        os.makedirs(os.path.join(td, 'contact'))
        os.makedirs(os.path.join(td, 'message'))
        c = sqlite3.connect(os.path.join(td, 'session', 'session.db'))
        c.execute('create table SessionTable(username text, last_timestamp int, summary text)')
        c.execute('insert into SessionTable values (?, ?, ?)', (user, 1760000000, 'hi'))
        c.commit()
        c.close()
        c = sqlite3.connect(os.path.join(td, 'contact', 'contact.db'))
        c.execute('create table contact(username text, remark text, nick_name text)')
        c.commit()
        c.close()
        table = 'Msg_' + hashlib.md5(user.encode()).hexdigest()
        c = sqlite3.connect(os.path.join(td, 'message', 'message_0.db'))
        c.execute(f'create table "{table}" (local_id integer)')
        c.executemany(f'insert into "{table}" values (?)', [(i,) for i in range(7)])
        c.commit()
        c.close()

        events = []
        store = ChatStore(td)
        items = store.sessions_with_counts(
            progress=lambda p, m='': events.append((p, m)))
        assert items and items[0]['username'] == user, items
        assert items[0]['count'] == 7, items
        assert events and events[-1][0] == 100, events
        assert any('统计会话消息数' in m for _p, m in events), events
        cache = os.path.join(td, 'session_counts.json')
        assert os.path.exists(cache), '应写入会话数量缓存'
        # 第二次走缓存，结果一致
        assert ChatStore(td).sessions_with_counts()[0]['count'] == 7
    print('OK: 会话消息数按库缓存')


def main():
    test_decrypt_reports_paged_progress()
    test_account_state_restores_prepared_targets()
    test_session_counts_are_cached()
    print('进度与准备状态测试全部通过')


if __name__ == '__main__':
    main()
