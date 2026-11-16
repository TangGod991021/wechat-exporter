# -*- coding: utf-8 -*-
"""配置原子写、媒体工具、数据根去重与密钥错误提示"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app.config as cfgmod  # noqa: E402
from app.core import keys  # noqa: E402
from app.core.discovery import _dedupe_root_entries  # noqa: E402
from app.core.media import file_md5  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def test_config_atomic_and_backup():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / 'config.json'
        with mock.patch.object(cfgmod, 'CONFIG_FILE', path):
            cfg = dict(cfgmod.DEFAULTS)
            cfg['wechat_root'] = r'D:\wechat'
            cfgmod.save_config(cfg)
            assert not path.with_suffix('.json.tmp').exists()
            assert cfgmod.load_config()['wechat_root'] == r'D:\wechat'

            path.write_text('{bad json', encoding='utf-8')
            loaded = cfgmod.load_config()
            assert loaded['wechat_root'] == '', loaded
            assert (Path(td) / 'config.json.bad').exists(), '损坏配置应备份'
    print('  ok  配置原子写入与损坏备份')


def test_file_md5_chunked():
    data = b'0123456789' * (1024 * 1024)  # 10 MB
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'big.mp4')
        with open(p, 'wb') as f:
            f.write(data)
        assert file_md5(p, chunk=1024 * 1024) == hashlib.md5(data).hexdigest()
    print('  ok  大文件分块 MD5')


def test_dedupe_root_entries():
    a = {'base_dir': r'C:\w\xwechat_files\wxid_a_1234', 'last_active': 1}
    b = {'base_dir': r'C:\w\xwechat_files\wxid_b_5678', 'last_active': 1}
    c = {'base_dir': r'D:\w\xwechat_files\wxid_c_abcd', 'last_active': 1}
    entries = [
        {'path': r'C:\w', 'accounts': [a, b]},
        {'path': r'C:\w\xwechat_files', 'accounts': [a, b]},
        {'path': r'D:\w\xwechat_files', 'accounts': [c]},
    ]
    out = _dedupe_root_entries(entries)
    assert [e['path'] for e in out] == [r'C:\w', r'D:\w\xwechat_files'], out
    print('  ok  父子数据根去重')


def test_keys_permission_message():
    db = {'rel': 'session/session.db', 'salt': 'aa'}
    with mock.patch.object(keys, 'collect_dbs', return_value=[db]), \
            mock.patch.object(keys, 'find_pids', return_value=[(1, [])]), \
            mock.patch.object(keys, 'config_cipher_scan',
                              return_value=({}, {'error': 'open-process-failed'})), \
            mock.patch.object(keys, 'plaintext_scan', return_value=({}, {})):
        found, meta = keys.extract_keys('unused')
    assert found == {}, found
    assert meta.get('error') == 'permission-denied', meta
    assert '管理员' in meta.get('message', ''), meta
    print('  ok  密钥权限失败提示')


def main():
    test_config_atomic_and_backup()
    test_file_md5_chunked()
    test_dedupe_root_entries()
    test_keys_permission_message()
    print('配置与工具测试全部通过')


if __name__ == '__main__':
    main()
