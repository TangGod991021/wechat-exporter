# -*- coding: utf-8 -*-
"""本地附件定位：文件名变体、大小/月份优先级、hardlink md5 映射"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.attachments import FileIndex, base_name, normalize_name  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def _write(path, size, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'x' * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_name_helpers():
    assert normalize_name('0820三五&amp;年糕.xlsx') == '0820三五&年糕.xlsx'
    assert base_name('工作交接.md (1).zip') == '工作交接.md.zip'
    assert base_name('报告（试行）(2).docx') == '报告（试行）.docx'
    print('  ok  文件名规范化')


def test_find_by_name_size_and_month():
    with tempfile.TemporaryDirectory() as td:
        file_dir = os.path.join(td, 'msg', 'file')
        attach_dir = os.path.join(td, 'msg', 'attach')
        old = _write(os.path.join(file_dir, '2026-03', '订单.xlsx'), 100,
                     mtime=1773000000)
        new = _write(os.path.join(file_dir, '2026-06', '订单.xlsx'), 200,
                     mtime=1780000000)
        _write(os.path.join(attach_dir, 'hash', '2026-06', 'Rec', 'x', 'F', '0',
                            '资料包.rar'), 300)
        idx = FileIndex(file_dir, attach_dir)

        hit = idx.find('订单.xlsx', size=200, ts=1780000000)
        assert hit and hit.path == new, hit
        # 大小不同时优先月份
        hit = idx.find('订单.xlsx', size=999, ts=1773500000)
        assert hit and hit.path == old, hit
        # 后缀变体：消息里是 压缩包.rar，本地是 压缩包 (1).rar
        _write(os.path.join(file_dir, '2026-07', '压缩包 (1).rar'), 300)
        idx = FileIndex(file_dir, attach_dir)
        hit = idx.find('压缩包.rar', size=300, ts=1783000000)
        assert hit and hit.name == '压缩包 (1).rar', hit
        # attach/F 能索引到
        hit = idx.find('资料包.rar')
        assert hit is not None and hit.month == '2026-06', hit
        assert idx.find('不存在.pdf') is None
    print('  ok  按名称/大小/月份定位')


def test_find_md5_hardlink():
    with tempfile.TemporaryDirectory() as td:
        file_dir = os.path.join(td, 'msg', 'file')
        attach_dir = os.path.join(td, 'msg', 'attach')
        _write(os.path.join(file_dir, '2026-08', '实际文件名.zip'), 50)
        db = os.path.join(td, 'hardlink.db')
        c = sqlite3.connect(db)
        c.execute('create table file_hardlink_info_v4 (md5 text, file_name text)')
        c.execute('insert into file_hardlink_info_v4 values (?, ?)',
                  ('a' * 32, '实际文件名.zip'))
        c.execute('insert into file_hardlink_info_v4 values (?, ?)',
                  ('b' * 32, '已被清理.zip'))
        c.commit()
        c.close()
        idx = FileIndex(file_dir, attach_dir, db)
        hit = idx.find_md5('a' * 32, size=50, ts=1786000000)
        assert hit and hit.name == '实际文件名.zip', hit
        # 同名文件不存在时不能退回到别的版本
        assert idx.find_md5('b' * 32) is None
    print('  ok  hardlink md5 映射')


if __name__ == '__main__':
    test_name_helpers()
    test_find_by_name_size_and_month()
    test_find_md5_hardlink()
    print('ATTACHMENT TESTS OK')
