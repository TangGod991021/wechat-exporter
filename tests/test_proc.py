# -*- coding: utf-8 -*-
"""子进程封装测试：确认 Windows 下默认隐藏控制台窗口。"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core import proc  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def run_case(cmd, **kwargs):
    captured = {}

    def fake(args, **kw):
        captured.update(kw)
        return 'ok'

    with mock.patch.object(proc.subprocess, 'run', fake):
        result = proc.run(cmd, **kwargs)
    return result, captured


def main():
    result, captured = run_case(['demo'])
    assert result == 'ok'
    if os.name == 'nt':
        assert captured.get('creationflags') == proc.CREATE_NO_WINDOW, captured
    print('OK: proc.run 默认附加 CREATE_NO_WINDOW')

    _, captured = run_case(['demo'], creationflags=0)
    assert captured.get('creationflags') == 0, captured
    print('OK: 显式 creationflags 不会被覆盖')


if __name__ == '__main__':
    main()
