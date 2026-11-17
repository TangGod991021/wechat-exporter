# -*- coding: utf-8 -*-
"""消息分库回归测试：同一会话的消息表跨 message_0/1.db 时必须合并导出。"""
import hashlib
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.export import ChatStore  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def _init_base(root):
    os.makedirs(os.path.join(root, 'session'))
    os.makedirs(os.path.join(root, 'contact'))
    os.makedirs(os.path.join(root, 'message'))
    c = sqlite3.connect(os.path.join(root, 'contact', 'contact.db'))
    c.execute('create table contact(username text, remark text, nick_name text)')
    c.execute('create table my_user_info(user_name text, nick_name text)')
    c.commit()
    c.close()
    c = sqlite3.connect(os.path.join(root, 'session', 'session.db'))
    c.execute('create table SessionTable(username text, last_timestamp int, summary text)')
    c.commit()
    c.close()


def _msg_db(path, table, rows, users):
    c = sqlite3.connect(path)
    c.execute('create table Name2Id(rowid integer primary key, user_name text)')
    c.executemany('insert into Name2Id(rowid, user_name) values (?, ?)',
                  list(enumerate(users, 1)))
    c.execute(f'create table "{table}" ('
              'local_id integer primary key, local_type integer, sort_seq integer, '
              'real_sender_id integer, create_time integer, message_content text, '
              'packed_info_data blob)')
    c.executemany(
        f'insert into "{table}" (local_id, local_type, sort_seq, real_sender_id, '
        'create_time, message_content) values (?, 1, ?, ?, ?, ?)', rows)
    c.commit()
    c.close()


def test_messages_merge_across_shards():
    user = 'demo_group@chatroom'
    table = 'Msg_' + hashlib.md5(user.encode()).hexdigest()
    with tempfile.TemporaryDirectory() as td:
        _init_base(td)
        msg_dir = os.path.join(td, 'message')
        # 模拟微信滚动分片：较早消息在 message_0.db，新消息在 message_1.db
        _msg_db(os.path.join(msg_dir, 'message_0.db'), table,
                [(1, 1000, 1, 1000, '旧消息1'),
                 (2, 1001, 1, 1001, '旧消息2'),
                 (3, 1002, 1, 1002, '旧消息3')],
                ['wxid_demo', user])
        _msg_db(os.path.join(msg_dir, 'message_1.db'), table,
                [(4, 2000, 1, 2000, '新消息1'),
                 (5, 2001, 1, 2001, '新消息2'),
                 (6, 2002, 1, 2002, '新消息3')],
                ['wxid_demo', user])
        c = sqlite3.connect(os.path.join(td, 'session', 'session.db'))
        c.execute('insert into SessionTable values (?, ?, ?)', (user, 2002, '新消息3'))
        c.commit()
        c.close()

        store = ChatStore(td)
        dbs, name = store.find_tables(user)
        assert len(dbs) == 2, dbs
        msgs = store.messages(user)
        texts = [m['text'] for m in msgs]
        assert texts == ['旧消息1', '旧消息2', '旧消息3', '新消息1', '新消息2', '新消息3'], texts
        assert store.message_count(user) == 6
        items = store.sessions_with_counts()
        assert items[0]['count'] == 6, items

        # 分页：使用 sort_seq 游标继续翻页，不丢同秒消息
        page1 = store.messages(user, limit=2)
        assert [m['text'] for m in page1] == ['新消息2', '新消息3'], page1
        first = page1[0]
        page2 = store.messages(user, limit=2, before_ts=first['ts'],
                               before_id=first['local_id'],
                               before_sort=first['sort_seq'])
        assert [m['text'] for m in page2] == ['旧消息3', '新消息1'], page2
    print('OK: 跨 message_0/1.db 的消息合并、计数与分页')


def test_biz_message_db_included():
    user = 'gh_demo123'
    table = 'Msg_' + hashlib.md5(user.encode()).hexdigest()
    with tempfile.TemporaryDirectory() as td:
        _init_base(td)
        _msg_db(os.path.join(td, 'message', 'biz_message_0.db'), table,
                [(1, 3000, 1, 3000, '公众号消息')], ['wxid_demo', user])
        store = ChatStore(td)
        assert store.message_count(user) == 1
        assert store.messages(user)[0]['text'] == '公众号消息'
    print('OK: 公众号 biz_message_*.db 也参与读取')


def main():
    test_messages_merge_across_shards()
    test_biz_message_db_included()
    print('消息分库测试全部通过')


if __name__ == '__main__':
    main()
