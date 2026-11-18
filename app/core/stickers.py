# -*- coding: utf-8 -*-
"""表情下载与缓存

微信 4.x 的本地表情缓存（cache/YYYY-MM/Emoticon/<md5>）是加密格式，
目前无法离线解密；但表情消息的 XML 自带腾讯 CDN 地址（base 47 的
cdnurl、appmsg type 8 的 emojiinfo），因此按消息里的地址下载原图，
并缓存到 media/<account>/stickers/ 下，重复导出不再联网。

所有下载都只允许腾讯表情 CDN 域名，避免被消息内容诱导访问任意地址。
"""
import hashlib
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.textutil import clean_url

ALLOWED_HOST_SUFFIXES = ('.qq.com', '.qpic.cn', '.gtimg.cn')
MAX_STICKER_BYTES = 32 * 1024 * 1024
STICKER_EXTS = ('.png', '.gif', '.jpg', '.jpeg', '.webp', '.bmp')


def detect_ext(data: bytes) -> str:
    """按文件头识别图片扩展名"""
    if data[:3] == b'\xff\xd8\xff':
        return '.jpg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return '.gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    if data[:2] == b'BM':
        return '.bmp'
    return ''


def safe_cdn_url(url: str) -> str:
    """只放行腾讯 CDN 的 http/https 地址，返回空串表示不可用"""
    url = clean_url(url)
    if not re.match(r'^https?://', url, re.I):
        return ''
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return ''
    host = (parsed.hostname or '').lower()
    if not host or parsed.username or parsed.password:
        return ''
    if not any(host == s.lstrip('.') or host.endswith(s)
               for s in ALLOWED_HOST_SUFFIXES):
        return ''
    return url


def sticker_stem(md5: str, url: str) -> str:
    md5 = re.sub(r'[^0-9a-fA-F]', '', md5 or '').lower()
    if len(md5) == 32:
        return md5
    return 'u' + hashlib.md5((url or '').encode()).hexdigest()


def find_cached(out_dir: str, md5: str, url: str = '') -> str:
    """返回已缓存的表情文件路径（任意已知扩展名）"""
    if not out_dir:
        return ''
    stem = sticker_stem(md5, url)
    for ext in STICKER_EXTS:
        p = os.path.join(out_dir, stem + ext)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            return p
    return ''


def download_one(md5: str, url: str, out_dir: str, timeout: float = 20.0) -> str:
    """下载单个表情；失败返回空串。已存在时直接返回缓存路径。"""
    cached = find_cached(out_dir, md5, url)
    if cached:
        return cached
    url = safe_cdn_url(url)
    if not url or not out_dir:
        return ''
    os.makedirs(out_dir, exist_ok=True)
    req = urllib.request.Request(
        url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_STICKER_BYTES + 1)
    except Exception:
        return ''
    if not data or len(data) > MAX_STICKER_BYTES:
        return ''
    ext = detect_ext(data)
    if not ext:
        return ''
    stem = sticker_stem(md5, url)
    dst = os.path.join(out_dir, stem + ext)
    fd, tmp = tempfile.mkstemp(prefix='.' + stem + '_', dir=out_dir)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, dst)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return ''
    return dst


def download_many(tasks, out_dir: str, workers: int = 8, progress=None):
    """批量下载表情。

    tasks: 可迭代的 (md5, url)；md5 为空时用 url 派生文件名。
    progress(done, total) 可选。
    """
    by_stem = {}
    for md5, url in tasks:
        if not safe_cdn_url(url):
            continue
        by_stem.setdefault(sticker_stem(md5, url), (md5, url))
    items = list(by_stem.values())
    total = len(items)
    ok = skipped = failed = 0
    if not total:
        return {'total': 0, 'ok': 0, 'skipped': 0, 'failed': 0, 'files': []}
    workers = max(1, min(16, workers or 8))
    paths = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(download_one, md5, url, out_dir): (md5, url)
                for md5, url in items}
        for fut in as_completed(futs):
            done += 1
            path = fut.result()
            if path:
                paths.append(path)
                ok += 1
            else:
                failed += 1
            if progress:
                progress(done, total)
    return {'total': total, 'ok': ok, 'skipped': skipped,
            'failed': failed, 'files': paths}


def account_sticker_dir(media_account_dir: str) -> str:
    return os.path.join(media_account_dir, 'stickers')
