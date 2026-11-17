# -*- coding: utf-8 -*-
"""SQLCipher 4 数据库解密（逐页 AES-256-CBC，保留 80 字节 reserve）"""
import hashlib
import hmac as hmac_mod
import os
import struct

from Crypto.Cipher import AES

from app.core.jobs import JobCancelled

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


def decrypt_database(db_path, out_path, enc_key, progress=None):
    """解密单个库：校验源库完整性，写临时文件成功后原子替换。

    progress(frac)：按页上报 0-1 进度（大库解密可能持续较久）。
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
    if progress:
        progress(0.0)
    try:
        with open(db_path, 'rb') as fin, open(tmp, 'wb') as fout:
            for pgno in range(1, total_pages + 1):
                page = fin.read(PAGE_SZ)
                if len(page) != PAGE_SZ:
                    return False  # 读取过程中源库被截断
                fout.write(decrypt_page(enc_key, page, pgno))
                # 每 512 页（2MB）上报一次，避免频繁回调拖慢解密
                if progress and pgno % 512 == 0:
                    progress(pgno / total_pages)
        with open(tmp, 'rb') as f:
            if f.read(16) != b'SQLite format 3\x00':
                return False
        os.replace(tmp, out_path)
        if progress:
            progress(1.0)
        return True
    except JobCancelled:
        raise
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
        if (name.startswith('message_') or name.startswith('media_')
                or name.startswith('biz_message_')):
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
    progress(pct, message)：按字节权重上报总进度；单个大库解密期间也会持续更新。
    """
    def report(pct, msg=''):
        if progress:
            progress(int(max(0, min(100, pct))), msg)

    results = []
    items = sorted(keys.items())
    if only_rels is not None:
        wanted = set(only_rels)
        items = [(rel, info) for rel, info in items if rel in wanted]
    total = len(items)
    if not total:
        return {'ok': 0, 'failed': 0, 'skipped': 0, 'total': 0, 'results': []}

    # 按源库大小加权，避免大库处理时进度条长时间不动
    weights = []
    for rel, _info in items:
        src = os.path.join(db_dir, rel.replace('/', os.sep))
        try:
            weights.append(max(1, os.path.getsize(src)))
        except OSError:
            weights.append(1)
    total_bytes = sum(weights)
    done_bytes = 0
    ok = failed = skipped = 0

    for idx, ((rel, info), weight) in enumerate(zip(items, weights)):
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
            report((done_bytes + weight) / total_bytes * 100, f'{rel} 已是最新，跳过')
        else:
            report(done_bytes / total_bytes * 100,
                   f'正在解密 {rel}（{idx + 1}/{total}）')
            try:
                sub = (lambda frac, _rel=rel, _w=weight:
                       report((done_bytes + _w * frac) / total_bytes * 100,
                              f'正在解密 {_rel} {int(frac * 100)}%'))
                if decrypt_database(src, dst, bytes.fromhex(info['enc_key']),
                                    progress=sub):
                    ok += 1
                    results.append({'rel': rel, 'status': 'ok'})
                else:
                    failed += 1
                    results.append({'rel': rel, 'status': 'hmac-failed'})
            except JobCancelled:
                raise
            except Exception as e:  # noqa: BLE001
                failed += 1
                results.append({'rel': rel, 'status': f'error: {e}'})
        done_bytes += weight
        report(done_bytes / total_bytes * 100,
               f'已处理 {idx + 1}/{total} 个数据库')

    return {'ok': ok, 'failed': failed, 'skipped': skipped,
            'total': total, 'results': results}
