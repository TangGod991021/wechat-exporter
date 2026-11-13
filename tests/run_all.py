# -*- coding: utf-8 -*-
"""运行全部离线测试（不含依赖真实微信/运行中服务的 smoke.py）"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    files = sorted(glob.glob(os.path.join(HERE, 'test_*.py')))
    failed = []
    for path in files:
        name = os.path.basename(path)
        print(f'=== {name} ===', flush=True)
        r = subprocess.run([sys.executable, path], cwd=ROOT)
        if r.returncode != 0:
            failed.append(name)
    print()
    if failed:
        print('FAILED:', ', '.join(failed))
        return 1
    print(f'ALL {len(files)} TEST FILES PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
