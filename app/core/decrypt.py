# -*- coding: utf-8 -*-
"""SQLCipher 4 数据库解密（逐页 AES-256-CBC，保留 80 字节 reserve）"""
import hashlib
import hmac as hmac_mod
import os
import struct

from Crypto.Cipher import AES

PAGE_SZ = 4096
KEY_SZ = 32
SALT_SZ = 16
IV_SZ = 16
HMAC_SZ = 64
RESERVE_SZ = 80
SQLITE_HDR = b'SQLite format 3\x00'


def derive_mac_key(enc_key, salt):
    mac_salt = bytes(b ^ 0x3a for b in salt)
    return hashlib.pbkdf2_hmac('sha512', enc_key, mac_salt, 2, dklen=KEY_SZ)


def decrypt_page(enc_key, page_data, pgno):
    iv = page_data[PAGE_SZ - RESERVE_SZ: PAGE_SZ - RESERVE_SZ + IV_SZ]
    if pgno == 1:
        encrypted = page_data[SALT_SZ: PAGE_SZ - RESERVE_SZ]
        decrypted = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(encrypted)
        return bytes(bytearray(SQLITE_HDR + decrypted + b'\x00' * RESERVE_SZ))
    encrypted = page_data[:PAGE_SZ - RESERVE_SZ]
    decrypted = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(encrypted)
    return decrypted + b'\x00' * RESERVE_SZ


def verify_page1(enc_key, page1):
    salt = page1[:SALT_SZ]
    mac_key = derive_mac_key(enc_key, salt)
    hm = hmac_mod.new(mac_key, page1[SALT_SZ: PAGE_SZ - RESERVE_SZ + IV_SZ],
                      hashlib.sha512)
    hm.update(struct.pack('<I', 1))
    return hm.digest() == page1[PAGE_SZ - HMAC_SZ: PAGE_SZ]


def decrypt_database(db_path, out_path, enc_key):
    """解密单个库：校验源库完整性，写临时文件成功后原子替换。

    返回 False 表示源库不完整（正在写入/被截断）或第 1 页校验失败。
    """
    file_size = os.path.getsize(db_path)
    # SQLite 库必须是整页；不足一页说明源库正在写入或被截断，直接判失败
    if file_size < PAGE_SZ or file_size % PAGE_SZ:
        return False
    total_pages = file_size // PAGE_SZ
    with open(db_path, 'rb') as f:
        page1 = f.read(PAGE_SZ)
    if len(page1) < PAGE_SZ or not verify_page1(enc_key, page1):
        return False
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + '.tmp'
    try:
        with open(db_path, 'rb') as fin, open(tmp, 'wb') as fout:
            for pgno in range(1, total_pages + 1):
                page = fin.read(PAGE_SZ)
                if len(page) != PAGE_SZ:
                    return False  # 读取过程中源库被截断
                fout.write(decrypt_page(enc_key, page, pgno))
        with open(tmp, 'rb') as f:
            if f.read(16) != b'SQLite format 3\x00':
                return False
        os.replace(tmp, out_path)
        return True
    except Exception:
        return False
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# 聊天导出所需的数据库（跳过 sns / favorite / fts 等无关库）
CORE_DB_RELS = ['session/session.db', 'contact/contact.db']
CHAT_DB_RELS = CORE_DB_RELS + ['message/message_0.db', 'message/media_0.db']


def chat_db_rels(db_dir: str) -> list:
    """按实际文件生成消息库列表，兼容 message_1.db 等分片。"""
    rels = list(CORE_DB_RELS)
    msg_dir = os.path.join(db_dir, 'message')
    try:
        names = sorted(os.listdir(msg_dir))
    except OSError:
        names = []
    for name in names:
        if not name.endswith('.db'):
            continue
        if name.startswith('message_') or name.startswith('media_'):
            rels.append('message/' + name)
    if not any(r.startswith('message/message_') for r in rels):
        rels.append('message/message_0.db')
    if not any(r.startswith('message/media_') for r in rels):
        rels.append('message/media_0.db')
    return rels


def decrypt_all(db_dir, out_dir, keys, progress=None, skip_fresh=True,
                only_rels=None):
    """keys: {rel: {enc_key, salt}} -> {ok, failed, total, results}

    only_rels 非空时只解密指定相对路径的数据库。
    """
    results = []
    items = sorted(keys.items())
    if only_rels is not None:
        wanted = set(only_rels)
        items = [(rel, info) for rel, info in items if rel in wanted]
    total = len(items)
    ok = failed = skipped = 0
    for i, (rel, info) in enumerate(items, 1):
        src = os.path.join(db_dir, rel.replace('/', os.sep))
        dst = os.path.join(out_dir, rel.replace('/', os.sep))
        fresh = False
        if skip_fresh and os.path.exists(dst):
            try:
                # mtime 新且大小一致才跳过；半截文件会因大小不符而重解
                fresh = (os.path.getmtime(dst) >= os.path.getmtime(src)
                         and os.path.getsize(dst) == os.path.getsize(src))
            except OSError:
                fresh = False
        if fresh:
            skipped += 1
            results.append({'rel': rel, 'status': 'skipped'})
        else:
            try:
                if decrypt_database(src, dst, bytes.fromhex(info['enc_key'])):
                    ok += 1
                    results.append({'rel': rel, 'status': 'ok'})
                else:
                    failed += 1
                    results.append({'rel': rel, 'status': 'hmac-failed'})
            except Exception as e:  # noqa: BLE001
                failed += 1
                results.append({'rel': rel, 'status': f'error: {e}'})
        if progress:
            progress(int(i / total * 100))
    return {'ok': ok, 'failed': failed, 'skipped': skipped,
            'total': total, 'results': results}
