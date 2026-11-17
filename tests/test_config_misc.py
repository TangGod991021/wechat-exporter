# -*- coding: utf-8 -*-
"""配置原子写、媒体工具、数据根去重与密钥错误提示"""
import hashlib
import json
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


def test_export_dir_portable():
    """导出目录在程序目录内时按相对路径保存，配置从别的电脑带过来也不会写错位置。"""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / 'app'
        base.mkdir()
        out = base / 'exports'
        out.mkdir()
        path = base / 'config.json'
        with mock.patch.object(cfgmod, 'BASE_DIR', base), \
                mock.patch.object(cfgmod, 'CONFIG_FILE', path):
            cfg = dict(cfgmod.DEFAULTS)
            cfg['export_dir'] = str(out)
            cfgmod.save_config(cfg)
            raw = json.loads(path.read_text(encoding='utf-8'))
            assert raw['export_dir'] == 'exports', raw['export_dir']
            loaded = cfgmod.load_config()
            assert loaded['export_dir'] == str(out), loaded['export_dir']

            # 绝对路径不存在（从别的电脑复制）→ 回退到启动器同级 exports/
            path.write_text(json.dumps({'export_dir': r'D:\not-here\exports'}),
                            encoding='utf-8')
            loaded = cfgmod.load_config()
            assert loaded['export_dir'] == str(base / 'exports'), loaded['export_dir']
    print('  ok  导出目录按相对程序目录保存与回退')


def test_bundled_tools_path():
    """内置 ffmpeg 目录应被前置到 PATH，并优先于系统安装版本。"""
    from app.core import tools
    with tempfile.TemporaryDirectory() as td:
        appdir = Path(td)
        bindir = appdir / 'ffmpeg'
        bindir.mkdir()
        (bindir / 'ffmpeg.exe').write_bytes(b'')
        (bindir / 'ffprobe.exe').write_bytes(b'')
        old_path = os.environ.get('PATH', '')
        try:
            with mock.patch.object(sys, 'frozen', True, create=True), \
                    mock.patch.object(sys, 'executable',
                                      str(appdir / 'WeChatExporter.exe')), \
                    mock.patch.object(tools, '_candidate_dirs',
                                      return_value=[bindir,
                                                    appdir / '_internal' / 'ffmpeg']):
                added = tools.ensure_tools_on_path()
                assert added == str(bindir), added
                assert os.environ['PATH'].split(os.pathsep)[0] == str(bindir)
                assert tools.bundled_ffmpeg().endswith('ffmpeg.exe')
                assert tools.bundled_ffprobe().endswith('ffprobe.exe')
        finally:
            os.environ['PATH'] = old_path
    print('  ok  内置 FFmpeg 目录注入 PATH')


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
    test_export_dir_portable()
    test_bundled_tools_path()
    test_file_md5_chunked()
    test_dedupe_root_entries()
    test_keys_permission_message()
    print('配置与工具测试全部通过')


if __name__ == '__main__':
    main()
