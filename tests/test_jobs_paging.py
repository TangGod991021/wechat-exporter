# -*- coding: utf-8 -*-
"""后台任务互斥/取消 与 消息预览复合游标测试"""
import hashlib
import os
import sqlite3
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.export import ChatStore  # noqa: E402
from app.core.jobs import JobBusy, JobManager  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def test_job_mutex_and_cancel():
    mgr = JobManager()
    started = threading.Event()

    def slow(job):
        started.set()
        for i in range(200):
            job.update(i // 2, f'step {i}')
            time.sleep(0.02)

    jid = mgr.start('demo', slow)
    assert started.wait(2), '任务未启动'
    try:
        mgr.start('demo', lambda job: None)
        raise AssertionError('同类任务应被拒绝')
    except JobBusy:
        pass
    # 不同类型可以并行
    other = mgr.start('other', lambda job: None)
    assert other

    assert mgr.cancel(jid) is True
    deadline = time.time() + 5
    while time.time() < deadline:
        data = mgr.get(jid)
        if data['status'] == 'cancelled':
            break
        time.sleep(0.05)
    assert data['status'] == 'cancelled', data
    assert mgr.cancel(jid) is False, '已结束任务不应能再次取消'
    print('  ok  任务互斥与取消')


def test_job_error_written_to_log():
    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, 'run.log')
        mgr = JobManager(log_file=log_path)

        def boom(job):
            raise ValueError('boom')

        jid = mgr.start('demo', boom)
        deadline = time.time() + 5
        while time.time() < deadline and mgr.get(jid)['status'] == 'running':
            time.sleep(0.05)
        assert mgr.get(jid)['status'] == 'error'
        for _ in range(100):
            if os.path.exists(log_path):
                break
            time.sleep(0.02)
        text = open(log_path, encoding='utf-8').read()
        assert 'FAILED' in text and 'ValueError' in text, text
    print('  ok  任务错误写入运行日志')


def test_paging_same_second():
    username = 'wxid_demo'
    table = 'Msg_' + hashlib.md5(username.encode()).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        msg_dir = os.path.join(tmp, 'message')
        os.makedirs(msg_dir)
        db = sqlite3.connect(os.path.join(msg_dir, 'message_0.db'))
        db.execute('create table Name2Id (user_name TEXT)')
        db.execute('insert into Name2Id values (?)', (username,))
        db.execute(f'create table "{table}" (local_id INTEGER, local_type INTEGER, '
                   'real_sender_id INTEGER, create_time INTEGER, '
                   'message_content TEXT, packed_info_data BLOB)')
        rows = [(1, 100), (2, 100), (3, 100), (4, 99)]
        for lid, ts in rows:
            db.execute(f'insert into "{table}" values (?,?,?,?,?,?)',
                       (lid, 1, 1, ts, f'msg{lid}', None))
        db.commit()
        db.close()

        store = ChatStore(tmp)
        first = store.messages(username, limit=2)
        assert [m['local_id'] for m in first] == [2, 3], first
        oldest = first[0]
        page2 = store.messages(username, limit=2,
                               before_ts=oldest['ts'],
                               before_id=oldest['local_id'])
        ids = [m['local_id'] for m in page2]
        # local_id=1 与边界同秒，必须能取到（页内按时间升序：99 秒在前）
        assert sorted(ids) == [1, 4], ids
        old_behavior = store.messages(username, limit=2, before_ts=oldest['ts'])
        assert [m['local_id'] for m in old_behavior] == [4], old_behavior
    print('  ok  同秒消息复合游标分页')


def main():
    test_job_mutex_and_cancel()
    test_job_error_written_to_log()
    test_paging_same_second()
    print('任务与分页测试全部通过')


if __name__ == '__main__':
    main()
