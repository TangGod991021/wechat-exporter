# -*- coding: utf-8 -*-
"""分享短链检测与解析

微信里的 B 站分享通常是 b23.tv 短链；短码可能被平台回收/过期，打开后
返回 `{"code":-404,"message":"啥都木有","ttl":1}`。这里在准备/导出时检测一次：

- 302 -> 直接视频地址：保存最终 `https://www.bilibili.com/video/BV...`，导出使用它
- 200 + JSON code -404：标记为失效，卡片点击改为按标题搜索
- 网络失败/超时：保持原链接，界面仍提供搜索备用入口

只对 b23.tv / bilibili.com 做网络请求，避免把消息里的任意地址当成探测目标。
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.textutil import clean_url

SHORT_HOST = 'b23.tv'
BILI_HOSTS = {'b23.tv', 'bilibili.com', 'www.bilibili.com', 'm.bilibili.com'}
CACHE_TTL = 7 * 24 * 3600
STATUS_VALID = 'valid'
STATUS_EXPIRED = 'expired'
STATUS_UNKNOWN = 'unknown'
STATUS_PENDING = 'pending'

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')


def _host(url):
    try:
        return (urllib.parse.urlparse(url).hostname or '').lower()
    except ValueError:
        return ''


def is_bilibili_short(url):
    return _host(clean_url(url)) in BILI_HOSTS


def is_short_link(url):
    return _host(clean_url(url)) == SHORT_HOST


def search_url(title, platform='bilibili'):
    """按标题构造搜索链接（目前仅 B 站）"""
    title = (title or '').strip()
    if not title:
        return ''
    keyword = urllib.parse.quote(title)
    if platform == 'bilibili':
        return f'https://search.bilibili.com/all?keyword={keyword}'
    return ''


def _extract_location(headers):
    loc = headers.get('Location') or headers.get('location') or ''
    if not loc:
        return ''
    return urllib.parse.urljoin('https://b23.tv', loc)


def _looks_expired(body):
    if not body or len(body) > 2048:
        return False
    text = body.decode('utf-8', 'replace').lower().replace(' ', '')
    return ('"code":-404' in text or '"code":-400' in text
            or '啥都木有' in text)


def resolve(url, timeout: float = 6.0):
    """检测短链，返回 (status, resolved_url)

    status ∈ valid / expired / unknown；resolved_url 仅在能拿到 BV 地址时非空。
    """
    url = clean_url(url)
    if not url or not is_bilibili_short(url):
        return STATUS_UNKNOWN, ''
    req = urllib.request.Request(url, headers={
        'User-Agent': _UA, 'Accept': 'text/html,application/json,*/*'})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            status = getattr(resp, 'status', 200)
            if 300 <= status < 400:
                loc = _extract_location(resp.headers)
                if loc:
                    return STATUS_VALID, _strip_tracking(loc)
                return STATUS_UNKNOWN, ''
            body = resp.read(2048)
            if _looks_expired(body):
                return STATUS_EXPIRED, ''
            return STATUS_VALID, url
    except urllib.error.HTTPError as e:
        loc = _extract_location(e.headers or {})
        if loc:
            return STATUS_VALID, _strip_tracking(loc)
        if e.code in (404, 410):
            return STATUS_EXPIRED, ''
        return STATUS_UNKNOWN, ''
    except Exception:
        return STATUS_UNKNOWN, ''


def _strip_tracking(url):
    """只保留视频路径，去掉分享统计参数"""
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return url
    if '/video/' in p.path:
        return f'{p.scheme}://{p.netloc}{p.path}'
    return url


def load_cache(path):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(path, cache):
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def status_of(cache, url):
    url = clean_url(url)
    ent = (cache or {}).get(url) or {}
    return ent.get('status', ''), ent.get('resolved', ''), ent.get('checked_at', 0)


def check_urls(urls, cache_path, timeout: float = 6.0, workers: int = 4,
               ttl: int = CACHE_TTL, progress=None):
    """批量检测短链并写入缓存，返回 {'url': {'status','resolved','checked_at'}}"""
    cache = load_cache(cache_path)
    now = time.time()
    todo = []
    for url in dict.fromkeys(clean_url(u) for u in urls if u):
        if not is_bilibili_short(url):
            continue
        ent = cache.get(url) or {}
        age = now - float(ent.get('checked_at', 0))
        if ent.get('status') in (STATUS_VALID, STATUS_EXPIRED) and age < ttl:
            continue
        # 网络失败的 unknown 缓存 1 小时，避免离线时每次导出都等待超时
        if ent.get('status') == STATUS_UNKNOWN and age < 3600:
            continue
        todo.append(url)
    if not todo:
        return {u: cache.get(u) or {} for u in urls if u}

    workers = max(1, min(8, workers or 4))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(resolve, u, timeout): u for u in todo}
        for fut in as_completed(futs):
            u = futs[fut]
            try:
                status, resolved = fut.result()
            except Exception:
                status, resolved = STATUS_UNKNOWN, ''
            cache[u] = {'status': status, 'resolved': resolved,
                        'checked_at': time.time()}
            done += 1
            if progress:
                progress(done, len(todo))
    save_cache(cache_path, cache)
    return {clean_url(u): cache.get(clean_url(u)) or {} for u in urls if u}


def apply_to_message(content, cache):
    """把检测结果写回消息内容，供 HTML/界面渲染"""
    if not isinstance(content, dict):
        return
    if content.get('kind') != 'video_share':
        return
    url = clean_url(content.get('url'))
    status, resolved, _ = status_of(cache, url)
    if status == STATUS_EXPIRED:
        content['link_expired'] = True
    elif status == STATUS_VALID and resolved:
        content['resolved_url'] = resolved
    if status:
        content['link_status'] = status


def apply_to_messages(msgs, cache):
    for m in msgs:
        apply_to_message(m.get('content') or {}, cache)
