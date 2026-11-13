# -*- coding: utf-8 -*-
"""账号目录发现测试：合成目录结构，验证选中上层目录后能递归找到账号"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.discovery import find_accounts  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def make_account(base):
    os.makedirs(os.path.join(base, 'db_storage'), exist_ok=True)
    with open(os.path.join(base, 'db_storage', 'message_0.db'), 'wb') as f:
        f.write(b'x' * 1024)


def check(root, expected, label):
    found = find_accounts(root)
    folders = [a['folder'] for a in found]
    assert len(found) == expected, f'{label}: 期望 {expected} 个账号，实际 {folders}'
    print(f'  ok  {label}: {folders}')


def main():
    with tempfile.TemporaryDirectory() as tmp:
        account = os.path.join(tmp, 'xwechat_files', 'wxid_demo_1234')
        make_account(account)

        check(tmp, 1, '选中上层父目录')
        check(os.path.join(tmp, 'xwechat_files'), 1, '选中数据根目录')
        check(account, 1, '直接选中账号目录')

        # 更深的自定义路径：微信改过存储位置
        deep = os.path.join(tmp, 'my_wechat_data', 'xwechat_files2', 'wxid_deep_abcd')
        make_account(deep)
        check(tmp, 2, '自定义深层路径（含 wechat 关键字）')
        check(os.path.join(tmp, 'my_wechat_data'), 1, '选中自定义路径的上一级')

        # 无关目录不应被误判
        os.makedirs(os.path.join(tmp, 'docs', 'notes'), exist_ok=True)
        found = find_accounts(os.path.join(tmp, 'docs'))
        assert found == [], f'无关目录误判: {found}'
        print('  ok  无关目录不误判')

    print('discovery 测试全部通过')


if __name__ == '__main__':
    main()
