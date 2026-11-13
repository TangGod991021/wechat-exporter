# -*- coding: utf-8 -*-
"""子进程调用工具：Windows 下隐藏控制台窗口。

打包后的程序是 GUI 子系统，调用 powershell / tasklist / ffmpeg 等控制台程序时，
Windows 会为每个子进程新建控制台窗口。统一附加 CREATE_NO_WINDOW，避免黑框闪烁。
"""
import os
import subprocess

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)


def run(cmd, **kwargs):
    """等价于 subprocess.run，在 Windows 上默认隐藏子进程控制台。"""
    if os.name == 'nt':
        kwargs.setdefault('creationflags', CREATE_NO_WINDOW)
    return subprocess.run(cmd, **kwargs)
