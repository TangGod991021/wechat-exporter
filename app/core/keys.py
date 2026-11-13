# -*- coding: utf-8 -*-
"""微信 4.x 数据库密钥提取

两条策略：
  1. Config.Cipher（4.1.11+）：内存中 "com.Tencent.WCDB.Config.Cipher" 对象的
     blob 被固定 32 字节掩码 XOR，解出 x'<enc_key><salt>'
  2. 明文缓存（4.0.x）：内存中存在 ASCII x'<enc_key><salt>'

算法参考 SmileGrassSky620/wechat-local-reader（MIT License）。
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import hmac as hmac_mod
import os
import re
import struct
import time

PAGE_SZ = 4096
KEY_SZ = 32
SALT_SZ = 16
IV_SZ = 16
HMAC_SZ = 64
RESERVE_SZ = 80
IV_OFFSET = PAGE_SZ - RESERVE_SZ

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH_W = 260
READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}
HEX_RE = re.compile(rb"x'([0-9a-fA-F]{64,192})'")

CONFIG_NEEDLE = b'com.Tencent.WCDB.Config.Cipher'
CONFIG_MASK = bytes.fromhex(
    'd2c7442458020000004889442450488b'
    '450048844c2448488944254048584c24'
)
CONFIG_BLOB_MAX = 1024
CONFIG_LITERAL_RE = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")
MAX_ADDR = 0x0000_8000_0000_0000
CHUNK = 2 * 1024 * 1024


class MBI(ctypes.Structure):
    _fields_ = [
        ('BaseAddress', ctypes.c_uint64), ('AllocationBase', ctypes.c_uint64),
        ('AllocationProtect', wt.DWORD), ('_pad1', wt.DWORD),
        ('RegionSize', ctypes.c_uint64), ('State', wt.DWORD),
        ('Protect', wt.DWORD), ('Type', wt.DWORD), ('_pad2', wt.DWORD),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
        ('th32DefaultHeapID', ctypes.c_void_p), ('th32ModuleID', wt.DWORD),
        ('cntThreads', wt.DWORD), ('th32ParentProcessID', wt.DWORD),
        ('pcPriClassBase', ctypes.c_long), ('dwFlags', wt.DWORD),
        ('szExeFile', ctypes.c_wchar * MAX_PATH_W),
    ]


def find_pids(image_name='Weixin.exe'):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1 or snap is None:
        return []
    out = []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
    while ok:
        if entry.szExeFile.lower() == image_name.lower():
            out.append((int(entry.th32ProcessID), int(entry.cntThreads)))
        ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def enumerate_regions(handle):
    regions = []
    addr = 0
    mbi = MBI()
    size = ctypes.sizeof(mbi)
    while addr < 0x7FFFFFFFFFFF:
        if not kernel32.VirtualQueryEx(handle, ctypes.c_uint64(addr),
                                       ctypes.byref(mbi), size):
            break
        if (mbi.State == MEM_COMMIT and mbi.Protect in READABLE
                and 0 < mbi.RegionSize <= 512 * 1024 * 1024):
            regions.append((int(mbi.BaseAddress), int(mbi.RegionSize)))
        nxt = int(mbi.BaseAddress) + int(mbi.RegionSize)
        if nxt <= addr:
            break
        addr = nxt
    return regions


def read_mem(handle, addr, size):
    buf = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    if kernel32.ReadProcessMemory(handle, ctypes.c_uint64(addr), buf, size,
                                  ctypes.byref(read)):
        return buf.raw[:read.value]
    return None


def mac_key_of(enc_key, salt):
    mac_salt = bytes(b ^ 0x3A for b in salt)
    return hashlib.pbkdf2_hmac('sha512', enc_key, mac_salt, 2, dklen=KEY_SZ)


def verify_key(enc_key, page1):
    salt = page1[:SALT_SZ]
    hmac_data = page1[SALT_SZ: IV_OFFSET + IV_SZ]
    stored = page1[PAGE_SZ - HMAC_SZ:]
    h = hmac_mod.new(mac_key_of(enc_key, salt), hmac_data, hashlib.sha512)
    h.update(struct.pack('<I', 1))
    return hmac_mod.compare_digest(h.digest(), stored)


def collect_dbs(db_dir):
    dbs = []
    for root, _dirs, files in os.walk(db_dir):
        for name in files:
            if not name.endswith('.db'):
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) < PAGE_SZ:
                    continue
                with open(path, 'rb') as fh:
                    page1 = fh.read(PAGE_SZ)
            except OSError:
                continue
            rel = os.path.relpath(path, db_dir).replace('\\', '/')
            dbs.append({'rel': rel, 'path': path, 'page1': page1,
                        'salt': page1[:SALT_SZ].hex()})
    dbs.sort(key=lambda d: d['rel'])
    return dbs


def _u64(buf, off):
    if off < 0 or off + 8 > len(buf):
        return 0
    return struct.unpack_from('<Q', buf, off)[0]


def _xor_repeat(data, mask):
    return bytes(v ^ mask[i % len(mask)] for i, v in enumerate(data))


def _iter_chunks(regions, read, chunk=CHUNK, overlap=0):
    for base, size in regions:
        off = 0
        tail = b''
        tail_base = base
        while off < size:
            take = min(chunk, size - off)
            data = read(base + off, take) or b''
            data_base = tail_base if tail else base + off
            merged = tail + data
            if merged:
                yield data_base, merged
                if overlap:
                    tail = merged[-overlap:]
                    tail_base = data_base + max(0, len(merged) - len(tail))
                else:
                    tail = b''
                    tail_base = base + off + take
            else:
                tail = b''
                tail_base = base + off + take
            off += take


def config_cipher_scan(pid):
    handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        return {}, {'error': 'open-process-failed'}
    try:
        regions = enumerate_regions(handle)

        def read(addr, size):
            return read_mem(handle, addr, size)

        needle_addrs = set()
        for base, data in _iter_chunks(regions, read, overlap=len(CONFIG_NEEDLE) - 1):
            pos = data.find(CONFIG_NEEDLE)
            while pos >= 0:
                needle_addrs.add(base + pos)
                pos = data.find(CONFIG_NEEDLE, pos + 1)

        stats = {'needle': len(needle_addrs), 'nodes': 0, 'blobs': 0, 'candidates': 0}
        if not needle_addrs:
            return {}, stats

        pairs = [struct.pack('<Q', a) + struct.pack('<Q', len(CONFIG_NEEDLE))
                 for a in needle_addrs]
        found = {}
        for base, data in _iter_chunks(regions, read, overlap=0x80):
            for pat in pairs:
                pos = data.find(pat)
                while pos >= 0:
                    qaddr = base + pos
                    node = read(qaddr - 0x10, 0x50)
                    if (node and len(node) >= 0x40
                            and _u64(node, 0x10) in needle_addrs
                            and _u64(node, 0x18) == len(CONFIG_NEEDLE)):
                        stats['nodes'] += 1
                        cfg = _u64(node, 0x28)
                        if 0x10000 <= cfg < MAX_ADDR:
                            obj = read(cfg + 0x88, 0x28)
                            if obj and len(obj) >= 0x18:
                                dptr, dlen = _u64(obj, 0x8), _u64(obj, 0x10)
                                if 0 < dlen <= CONFIG_BLOB_MAX and 0x10000 <= dptr < MAX_ADDR:
                                    blob = read(dptr, int(dlen))
                                    if blob and len(blob) == dlen:
                                        stats['blobs'] += 1
                                        decoded = _xor_repeat(blob, CONFIG_MASK)
                                        for m in CONFIG_LITERAL_RE.finditer(decoded):
                                            run = m.group(1).decode('ascii').lower()
                                            stats['candidates'] += 1
                                            if len(run) >= 96:
                                                found[run[64:96]] = run[:64]
                    pos = data.find(pat, pos + 1)
        stats['matched'] = len(found)
        return found, stats
    finally:
        kernel32.CloseHandle(handle)


def plaintext_scan(pid, dbs, progress=None):
    """4.0 路径：扫描明文 x'<hex>'，并用 HMAC 验证"""
    handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        return {}, {'error': 'open-process-failed'}
    try:
        salt_to_dbs = {}
        for d in dbs:
            salt_to_dbs.setdefault(d['salt'], []).append(d)
        regions = enumerate_regions(handle)
        found = {}
        pending = set(salt_to_dbs)
        total = sum(s for _b, s in regions) or 1
        done = 0
        t0 = time.time()
        for base, size in regions:
            if not pending:
                break
            off = 0
            overlap = 320
            while off < size:
                take = min(8 * 1024 * 1024, size - off)
                data = read_mem(handle, base + off, take)
                if data:
                    for m in HEX_RE.finditer(data):
                        h = m.group(1).decode('ascii')
                        n = len(h)
                        if n == 96:
                            enc, salt = h[:64], h[64:]
                            if salt in pending and verify_key(
                                    bytes.fromhex(enc), salt_to_dbs[salt][0]['page1']):
                                found[salt] = enc
                                pending.discard(salt)
                        elif n == 64:
                            key = bytes.fromhex(h)
                            for salt in list(pending):
                                if verify_key(key, salt_to_dbs[salt][0]['page1']):
                                    found[salt] = h
                                    pending.discard(salt)
                                    break
                        else:
                            enc, salt = h[:64], h[-32:]
                            if salt in pending and verify_key(
                                    bytes.fromhex(enc), salt_to_dbs[salt][0]['page1']):
                                found[salt] = enc
                                pending.discard(salt)
                done += take
                if progress:
                    progress(min(99, int(done / total * 100)))
                if take < 8 * 1024 * 1024:
                    break
                off += take - overlap
        return found, {'seconds': round(time.time() - t0, 1), 'matched': len(found)}
    finally:
        kernel32.CloseHandle(handle)


def extract_keys(db_dir, progress=None):
    """返回 (keys_by_rel, meta)

    keys_by_rel: {rel_path: {'enc_key': hex, 'salt': hex}}
    """
    dbs = collect_dbs(db_dir)
    if not dbs:
        return {}, {'error': 'no-db', 'message': '没有找到 .db 文件'}
    pids = find_pids()
    if not pids:
        return {}, {'error': 'weixin-not-running',
                    'message': '微信未运行，请先打开并登录微信'}

    # 策略 1：4.1.11+ Config.Cipher
    for i, (pid, _threads) in enumerate(pids):
        found, stats = config_cipher_scan(pid)
        if found:
            keys = {d['rel']: {'enc_key': found[d['salt']], 'salt': d['salt']}
                    for d in dbs if d['salt'] in found}
            if keys:
                missing = [d['rel'] for d in dbs if d['salt'] not in found]
                return keys, {'mode': 'config-cipher', 'pid': pid,
                              'stats': stats, 'missing': missing}
        if progress:
            progress(int((i + 1) / len(pids) * 50))

    # 策略 2：4.0 明文缓存
    for pid, _threads in pids:
        found, stats = plaintext_scan(pid, dbs, progress)
        if found:
            keys = {d['rel']: {'enc_key': found[d['salt']], 'salt': d['salt']}
                    for d in dbs if d['salt'] in found}
            if keys:
                missing = [d['rel'] for d in dbs if d['salt'] not in found]
                return keys, {'mode': 'plaintext', 'pid': pid,
                              'stats': stats, 'missing': missing}

    return {}, {'error': 'key-not-found',
                'message': '未能提取到密钥。请确认微信已登录，或该版本尚未适配。'}
