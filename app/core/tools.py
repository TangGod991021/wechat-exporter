# -*- coding: utf-8 -*-
"""内置命令行工具的定位与 PATH 注入（FFmpeg / ffprobe）。

打包时 ffmpeg.exe / ffprobe.exe 放在产物目录的 `ffmpeg/` 子目录
（PyInstaller onedir 下通常是 `_internal/ffmpeg/`）；开发环境下放在
`packaging/ffmpeg/`。启动时把该目录前置到 PATH，子进程即可直接用
`ffmpeg` / `ffprobe` 调用内置版本，无需用户自行安装。
"""
import os
import sys
from pathlib import Path


def _candidate_dirs():
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).resolve().parent
        meipass = getattr(sys, '_MEIPASS', '')
        out = [base / 'ffmpeg', base / '_internal' / 'ffmpeg']
        if meipass:
            out.append(Path(meipass) / 'ffmpeg')
        return out
    root = Path(__file__).resolve().parent.parent.parent
    return [root / 'packaging' / 'ffmpeg']


def bundled_tools_dir() -> Path | None:
    """返回包含 ffmpeg 可执行文件的目录；不存在时返回 None"""
    exe = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
    for d in _candidate_dirs():
        if (d / exe).is_file():
            return d
    return None


def bundled_ffmpeg() -> str:
    d = bundled_tools_dir()
    if not d:
        return ''
    exe = d / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    return str(exe)


def bundled_ffprobe() -> str:
    d = bundled_tools_dir()
    if not d:
        return ''
    exe = d / ('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
    return str(exe) if exe.is_file() else ''


def ensure_tools_on_path() -> str:
    """把内置工具目录前置到 PATH，返回该目录（没有内置工具时为 ''）"""
    d = bundled_tools_dir()
    if not d:
        return ''
    path = str(d)
    parts = [p for p in os.environ.get('PATH', '').split(os.pathsep) if p]
    if path not in parts:
        os.environ['PATH'] = path + os.pathsep + os.environ.get('PATH', '')
    return path
