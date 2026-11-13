# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：pyinstaller packaging/app.spec"""
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

datas = []
binaries = []
hiddenimports = []

for pkg in ('webview',):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += ['clr', 'pilk', 'zstandard', 'Crypto', 'PIL', 'av',
                  'multiprocessing', 'multiprocessing.spawn']

datas += [(os.path.join(ROOT, 'webui', 'dist'), os.path.join('webui', 'dist'))]

a = Analysis(
    [os.path.join(ROOT, 'run.py')],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='微信聊天记录导出',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, 'packaging', 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='微信聊天记录导出',
)
