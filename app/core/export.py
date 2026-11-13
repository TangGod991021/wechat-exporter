# -*- coding: utf-8 -*-
"""会话解析与聊天记录导出（微信 4.x schema）"""
import csv
import glob
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime

import zstandard as zstd

from app.core.message_parser import parse_content, split_local_type
from app.core.media import load_video_index

TYPE_NAMES = {
    1: 'text', 3: 'image', 34: 'voice', 43: 'video', 47: 'sticker',
    48: 'location', 49: 'app', 50: 'call', 10000: 'system', 10002: 'system',
}

_zstd = zstd.ZstdDecompressor()


def dec(v):
    if isinstance(v, bytes):
        if v[:4] == b'\x28\xb5\x2f\xfd':
            try:
                return _zstd.decompress(v).decode('utf-8', 'replace')
            except Exception:
                return v.decode('utf-8', 'replace')
        return v.decode('utf-8', 'replace')
    return v or ''


class ChatStore:
    """一个账号的已解密数据访问入口"""

    def __init__(self, data_dir, images_dir='', voices_dir='', my_wxid='',
                 video_roots=None, video_cache='', video_playback_dir=''):
        self.data_dir = data_dir
        self.images_dir = images_dir
        self.voices_dir = voices_dir
        self.my_wxid = my_wxid
        self.video_roots = video_roots or []
        self.video_cache = video_cache
        self.video_playback_dir = video_playback_dir
        self.session_db = os.path.join(data_dir, 'session', 'session.db')
        self.contact_db = os.path.join(data_dir, 'contact', 'contact.db')
        self.media_db = os.path.join(data_dir, 'message', 'media_0.db')
        self.message_dbs = sorted(glob.glob(os.path.join(data_dir, 'message', 'message_*.db')))
        self._names = None
        self._image_index = None
        self._video_index = None

    # ---------- 基础信息 ----------
    def contacts(self):
        out = {}
        if not os.path.exists(self.contact_db):
            return out
        c = sqlite3.connect(self.contact_db)
        try:
            for username, remark, nick in c.execute(
                    'select username, remark, nick_name from contact'):
                out[username] = remark or nick or username
        finally:
            c.close()
        return out

    def self_info(self):
        info = {'wxid': self.my_wxid, 'nickname': ''}
        if not os.path.exists(self.contact_db):
            return info
        row = None
        try:
            c = sqlite3.connect(self.contact_db)
            try:
                row = c.execute(
                    'select user_name, nick_name from my_user_info limit 1').fetchone()
            except sqlite3.Error:
                row = None
            c.close()
        except Exception:
            pass
        if row:
            info['wxid'] = row[0] or self.my_wxid
            info['nickname'] = row[1] or ''
        if not info['nickname']:
            name = self.contacts().get(self.my_wxid, '')
            if name:
                info['nickname'] = name
        return info

    def sessions(self):
        if not os.path.exists(self.session_db):
            return []
        contacts = self.contacts()
        c = sqlite3.connect(self.session_db)
        try:
            rows = c.execute(
                'select username, last_timestamp, summary from SessionTable '
                'order by last_timestamp desc').fetchall()
        finally:
            c.close()
        out = []
        for username, ts, summary in rows:
            if username.endswith('@openim'):
                continue
            out.append({
                'username': username,
                'name': contacts.get(username, username),
                'is_group': username.endswith('@chatroom'),
                'last_time': int(ts),
                'last_time_text': datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M') if ts else '',
                'summary': summary or '',
            })
        return out

    def find_table(self, username):
        h = hashlib.md5(username.encode()).hexdigest()
        for db in self.message_dbs:
            c = sqlite3.connect(db)
            try:
                row = c.execute(
                    "select name from sqlite_master where type='table' and name=?",
                    (f'Msg_{h}',)).fetchone()
            finally:
                c.close()
            if row:
                return db, row[0]
        return None, None

    def message_count(self, username):
        db, table = self.find_table(username)
        if not table:
            return 0
        c = sqlite3.connect(db)
        try:
            return c.execute(f'select count(*) from "{table}"').fetchone()[0]
        finally:
            c.close()

    # ---------- 媒体 ----------
    def image_index(self):
        if self._image_index is None:
            self._image_index = {}
            if self.images_dir and os.path.isdir(self.images_dir):
                rank = {'': 0, '_h': 1, '_t': 2}
                for dirpath, _dirs, names in os.walk(self.images_dir):
                    for n in names:
                        stem, ext = os.path.splitext(n)
                        if ext.lower() not in ('.jpg', '.png', '.webp', '.gif'):
                            continue
                        suffix, base = '', stem
                        for s in ('_h', '_t'):
                            if stem.endswith(s):
                                suffix, base = s, stem[:-2]
                                break
                        key = base.lower()
                        cur = self._image_index.get(key)
                        if cur is None or rank[suffix] < cur[0]:
                            self._image_index[key] = (rank[suffix], os.path.join(dirpath, n))
                self._image_index = {k: v[1] for k, v in self._image_index.items()}
        return self._image_index

    def _find_image(self, md5):
        return self.image_index().get((md5 or '').lower())

    def video_index(self):
        if self._video_index is None:
            if self.video_cache and os.path.exists(self.video_cache):
                self._video_index = load_video_index(self.video_cache)
            else:
                self._video_index = {}
        return self._video_index

    def _find_video(self, md5):
        md5 = (md5 or '').lower()
        if not md5:
            return None
        if self.video_playback_dir:
            h264 = os.path.join(self.video_playback_dir, md5 + '.mp4')
            if os.path.exists(h264):
                return h264
        return self.video_index().get(md5)

    def _find_voice(self, chat, local_id):
        if not self.voices_dir:
            return None
        safe = re.sub(r'[\\/:*?"<>|]', '_', chat)[:80]
        hits = glob.glob(os.path.join(self.voices_dir, safe, f'*_{local_id}.wav'))
        return hits[0] if hits else None

    # ---------- 消息 ----------
    def messages(self, username, since=None, until=None, limit=None, before_ts=None):
        db, table = self.find_table(username)
        if not table:
            return []
        c = sqlite3.connect(db)
        try:
            names = {rid: u for rid, u in c.execute('select rowid, user_name from Name2Id')}
            conds, params = [], []
            if since:
                conds.append('create_time >= ?')
                params.append(int(datetime.strptime(since, '%Y-%m-%d').timestamp()))
            if until:
                conds.append('create_time <= ?')
                params.append(int(datetime.strptime(until, '%Y-%m-%d').timestamp()) + 86399)
            if before_ts:
                conds.append('create_time < ?')
                params.append(int(before_ts))
            where = ('where ' + ' and '.join(conds)) if conds else ''
            sql = f'select local_id, local_type, real_sender_id, create_time, ' \
                  f'message_content, packed_info_data from "{table}" {where} ' \
                  f'order by create_time desc, local_id desc'
            if limit:
                sql += f' limit {int(limit)}'
            rows = c.execute(sql, params).fetchall()
        finally:
            c.close()
        contacts = self.contacts()
        out = [self._parse(username, names, contacts, r) for r in rows]
        out.reverse()
        return out

    def _parse(self, chat, names, contacts, row):
        local_id, ltype, sender_id, ctime, content_raw, packed = row
        content = dec(content_raw)
        base, sub = split_local_type(ltype)

        sender = names.get(sender_id, '') if sender_id else ''
        if sender == self.my_wxid:
            display = '我'
        elif sender:
            display = contacts.get(sender, sender)
        else:
            display = '系统'

        parsed = parse_content(ltype, content)
        kind = parsed.get('kind', 'text')
        text = parsed.get('text', '')
        media = ''
        poster = ''

        if kind == 'chat_history':
            for rec in parsed.get('records', []):
                md5 = rec.get('md5') or rec.get('thumb_md5')
                if rec.get('kind') == 'video':
                    rec['media'] = self._find_video(md5) or ''
                elif rec.get('kind') == 'image':
                    rec['media'] = self._find_image(md5) or ''
                else:
                    rec['media'] = ''

        if base == 1:
            m = re.match(r'^(wxid_[A-Za-z0-9]+|[A-Za-z0-9_-]+@chatroom):\n', text)
            if m:
                text = text[m.end():]
        elif base == 3:
            md5 = None
            if packed:
                m = re.search(rb'([0-9a-fA-F]{32})', packed)
                md5 = m.group(1).decode('ascii').lower() if m else None
            if not md5:
                m = re.search(r'md5="([0-9a-fA-F]{32})"', content)
                md5 = m.group(1) if m else None
            media = self._find_image(md5) or ''
        elif base == 34:
            m = re.search(r'voicelength="(\d+)"', content)
            secs = int(m.group(1)) / 1000 if m else 0
            media = self._find_voice(contacts.get(chat, chat), local_id) or ''
            text = f'[语音 {secs:.0f}s]' if secs else '[语音]'
        elif base == 43:
            m = re.search(r'md5="([0-9a-fA-F]{32})"', content)
            md5 = m.group(1).lower() if m else None
            media = self._find_video(md5) or ''
            if media:
                stem = os.path.splitext(media)[0]
                for cand in (stem + '.jpg', stem + '_thumb.jpg'):
                    if os.path.exists(cand):
                        poster = cand
                        break
            mlen = re.search(r'length="(\d+)"', content)
            if mlen:
                n = int(mlen.group(1))
                if n >= 1024 * 1024:
                    text = f'[视频 {n / 1024 / 1024:.1f} MB]'
            if not media:
                text = (text or '[视频]') + '（未缓存到本地）'

        return {
            'local_id': local_id,
            'time': datetime.fromtimestamp(ctime).strftime('%Y-%m-%d %H:%M:%S'),
            'ts': ctime,
            'type': TYPE_NAMES.get(base, f'type_{base}'),
            'local_type': ltype,
            'sub_type': sub,
            'kind': kind,
            'sender': display,
            'sender_wxid': sender,
            'text': text,
            'media': media,
            'poster': poster,
            'content': parsed,
        }


URL_RE = re.compile(r'(https?://[^\s<"]+)')


def linkify(s):
    """先转义再识别链接，避免注入"""
    esc = html.escape(s or '')
    return URL_RE.sub(
        lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener">{m.group(1)}</a>',
        esc)


def _domain(url):
    m = re.match(r'https?://([^/]+)', url or '')
    return m.group(1) if m else ''


def _record_html(c, uri_fn=None):
    uri_fn = uri_fn or _default_uri
    rows = []
    for r in c.get('records', []):
        head = (f'<div class="ri-head"><span class="ri-sender">'
                f'{html.escape(r.get("sender", ""))}</span>'
                f'<span class="ri-time">{html.escape(r.get("time", ""))}</span></div>')
        body = f'<div class="ri-text">{linkify(r.get("text", ""))}</div>'
        size = ''
        if r.get('size') and r.get('kind') not in ('text', 'image', 'voice', 'sticker'):
            size = f'<div class="ri-size">{html.escape(r["size"])}</div>'
        media_html = ''
        if r.get('media'):
            uri = uri_fn(r['media'])
            low = r['media'].lower()
            if low.endswith('.mp4'):
                media_html = f'<video class="ri-img" controls src="{uri}"></video>'
            elif low.endswith('.wav'):
                media_html = f'<audio controls src="{uri}"></audio>'
            else:
                media_html = f'<img class="ri-img" src="{uri}" loading="lazy">'
        rows.append(f'<div class="record-item">{head}{body}{size}{media_html}</div>')
    title = html.escape(c.get('title') or '聊天记录')
    count = len(c.get('records', []))
    return (f'<details class="record"><summary><span class="rec-title">💬 {title}</span>'
            f'<span class="rec-count">{count} 条 · 点击展开</span></summary>'
            f'<div class="record-list">{"".join(rows)}</div></details>')


def _default_uri(path):
    return 'file:///' + path.replace('\\', '/').replace(' ', '%20')


def _rich_body(m, uri_fn=None):
    """按 kind 生成气泡内部 HTML"""
    uri_fn = uri_fn or _default_uri
    c = m.get('content') or {}
    kind = m.get('kind', 'text')
    if kind == 'chat_history' and c.get('records'):
        return _record_html(c, uri_fn)
    if kind == 'quote':
        q = c.get('quote') or {}
        return (
            f'<div class="quote"><div class="q-src">{html.escape(q.get("sender", ""))}</div>'
            f'<div class="q-text">{linkify(q.get("text", ""))}</div></div>'
            f'<div class="reply">{linkify(c.get("reply") or m.get("text", ""))}</div>')
    if kind == 'link':
        href = c.get('url') or ''
        title_html = (f'<a href="{html.escape(href)}" target="_blank" rel="noopener">'
                      f'{linkify(c.get("title") or href)}</a>') if href else linkify(c.get('title', ''))
        des = f'<div class="card-des">{linkify(c.get("des", ""))}</div>' if c.get('des') else ''
        meta = f'<div class="card-meta">{html.escape(_domain(href))}</div>' if href else ''
        return f'<div class="card"><div class="card-title">{title_html}</div>{des}{meta}</div>'
    if kind == 'file':
        meta = f'<div class="card-meta">{html.escape(c.get("size", ""))}</div>' if c.get('size') else ''
        return (f'<div class="card"><div class="card-title">📄 '
                f'{html.escape(c.get("title", m.get("text", "")))}</div>{meta}</div>')
    if kind in ('miniprogram', 'music', 'video_share', 'chat_history',
                'transfer', 'redpacket', 'kf_template', 'app'):
        icon = {'miniprogram': '🧩', 'music': '🎵', 'video_share': '🎬',
                'chat_history': '💬', 'transfer': '💰', 'redpacket': '🧧',
                'kf_template': '📢', 'app': '📦'}.get(kind, '📦')
        des = f'<div class="card-des">{linkify(c.get("des", ""))}</div>' if c.get('des') else ''
        app = f'<div class="card-meta">{html.escape(c.get("app", ""))}</div>' if c.get('app') else ''
        return (f'<div class="card"><div class="card-title">{icon} '
                f'{html.escape(c.get("title") or m.get("text", ""))}</div>{des}{app}</div>')
    return linkify(m.get('text', ''))


def write_html(path, title, msgs, uri_fn=None):
    uri_fn = uri_fn or _default_uri

    def esc(s):
        return html.escape(s or '').replace('\n', '<br>')

    parts = [f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>{esc(title)} 聊天记录</title>
<style>
body{{background:#f2f3f5;font-family:"Microsoft YaHei",sans-serif;margin:0;padding:20px}}
h2{{text-align:center;color:#333}}
.msg{{margin:10px 0;display:flex;flex-direction:column}}
.meta{{font-size:12px;color:#999;margin-bottom:2px}}
.bubble{{background:#fff;border-radius:10px;padding:8px 12px;max-width:70%;width:fit-content;
box-shadow:0 1px 3px rgba(0,0,0,.06);white-space:normal;word-break:break-word;line-height:1.6}}
.me{{align-items:flex-end}} .me .bubble{{background:#95ec69}}
.me .meta{{text-align:right}}
img.chat-img{{max-width:320px;border-radius:8px;display:block;margin-top:4px}}
video.chat-video{{max-width:360px;border-radius:8px;display:block;margin-top:4px;background:#000}}
audio{{max-width:260px;height:32px;margin-top:4px}}
.sys{{text-align:center;color:#999;font-size:12px;margin:8px 0}}
a{{color:#576b95;text-decoration:none}}
.quote{{background:#f5f5f5;border-left:3px solid #d0d0d0;border-radius:6px;
padding:6px 10px;margin-bottom:6px;font-size:13px;color:#666}}
.q-src{{font-weight:600;color:#888;font-size:12px}}
.q-text{{margin-top:2px}}
.card{{border:1px solid #e6e6e6;border-radius:8px;padding:10px 12px;background:#fafafa;
max-width:420px;width:fit-content;min-width:180px}}
.card-title{{font-weight:600;color:#333}}
.card-des{{font-size:12px;color:#888;margin-top:4px}}
.card-meta{{font-size:12px;color:#9a9a9a;margin-top:6px}}
.record{{border:1px solid #e6e6e6;border-radius:8px;background:#fafafa;max-width:480px}}
.record summary{{cursor:pointer;padding:10px 12px;list-style:none;display:flex;
justify-content:space-between;align-items:center;gap:10px}}
.record summary::-webkit-details-marker{{display:none}}
.rec-title{{font-weight:600;color:#333}}
.rec-count{{font-size:12px;color:#999;flex:none}}
.record-list{{border-top:1px solid #eee;max-height:420px;overflow:auto;padding:6px 12px}}
.record-item{{padding:8px 0;border-bottom:1px dashed #eee}}
.record-item:last-child{{border-bottom:none}}
.ri-head{{display:flex;justify-content:space-between;font-size:12px;color:#999;margin-bottom:2px}}
.ri-sender{{font-weight:600;color:#666}}
.ri-text{{font-size:13px;color:#333;word-break:break-word}}
.ri-size{{font-size:12px;color:#aaa;margin-top:2px}}
.ri-img{{max-width:220px;border-radius:6px;margin-top:4px;display:block}}
</style></head><body><h2>{esc(title)} 聊天记录（{len(msgs)} 条）</h2>"""]
    for m in msgs:
        kind = m.get('kind', 'text')
        if m['sender'] in ('系统', '') or kind in ('system', 'pat', 'unsupported'):
            parts.append(f'<div class="sys">{esc(m["time"])} {linkify(m["text"])}</div>')
            continue
        cls = 'msg me' if m['sender'] == '我' else 'msg'
        body = _rich_body(m, uri_fn)
        if m['media']:
            uri = uri_fn(m['media'])
            low = m['media'].lower()
            if low.endswith('.wav'):
                body += f'<br><audio controls src="{uri}"></audio>'
            elif low.endswith('.mp4'):
                poster_attr = ''
                if m.get('poster'):
                    poster_attr = f' poster="{uri_fn(m["poster"])}"'
                body += (f'<br><video class="chat-video" controls{poster_attr} '
                         f'src="{uri}"></video>')
            else:
                body += f'<br><img class="chat-img" src="{uri}" loading="lazy">'
        parts.append(
            f'<div class="{cls}"><div class="meta">{esc(m["sender"])} · {esc(m["time"])}</div>'
            f'<div class="bubble">{body}</div></div>')
    parts.append('</body></html>')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))


IMAGE_EXTS = ('.jpg', '.png', '.webp', '.gif')
MEDIA_KIND_DIR = {'.wav': 'audio', '.mp4': 'videos'}


def _media_kind_dir(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in MEDIA_KIND_DIR:
        return MEDIA_KIND_DIR[ext]
    if ext in IMAGE_EXTS:
        return 'images'
    return 'files'


def _media_name(src, ts, kind):
    stem = os.path.splitext(os.path.basename(src))[0]
    ext = os.path.splitext(src)[1].lower()
    if ts:
        try:
            dt = datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
        except (OSError, ValueError):
            dt = 'unknown'
    else:
        dt = 'unknown'
    if kind == 'audio':
        digits = re.sub(r'\D', '', stem.split('_')[-1])
        hint = (digits or '0').zfill(4)[-8:]
    else:
        m = re.search(r'([0-9a-f]{32})', stem)
        hint = m.group(1)[:8] if m else re.sub(r'[^0-9a-zA-Z]', '', stem)[-8:]
    return f'{dt}_{hint}{ext}'


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
        return
    except OSError:
        pass
    shutil.copy2(src, dst)


def _unique_dir(parent, name):
    path = os.path.join(parent, name)
    if not os.path.exists(path):
        return path
    i = 2
    while os.path.exists(f'{path}_{i}'):
        i += 1
    return f'{path}_{i}'


def _collect_media(msgs, chat_dir, progress=None):
    """把消息实际引用的媒体复制/硬链接到会话目录"""
    tasks = []
    for m in msgs:
        if m.get('media'):
            tasks.append((m['media'], m.get('ts')))
        if m.get('poster'):
            tasks.append((m['poster'], m.get('ts')))
        for r in (m.get('content') or {}).get('records', []):
            if r.get('media'):
                tasks.append((r['media'], m.get('ts')))
    media_map = {}
    counts = {'images': 0, 'videos': 0, 'audio': 0, 'files': 0}
    total = len(tasks)
    for i, (src, ts) in enumerate(tasks, 1):
        if not src or src in media_map or not os.path.exists(src):
            continue
        kind = _media_kind_dir(src)
        name = _media_name(src, ts, kind)
        dest_dir = os.path.join(chat_dir, kind)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, name)
        base, ext = os.path.splitext(name)
        n = 2
        while os.path.exists(dest):
            dest = os.path.join(dest_dir, f'{base}_{n}{ext}')
            n += 1
        try:
            _link_or_copy(src, dest)
        except OSError:
            continue
        media_map[src] = f'{kind}/{os.path.basename(dest)}'
        counts[kind] = counts.get(kind, 0) + 1
        if progress and i % 20 == 0:
            progress(int(i / total * 100) if total else 100, f'复制媒体 {i}/{total}')
    return media_map, counts


def _relativize(msgs, media_map):
    out = []
    for m in msgs:
        mm = dict(m)
        if m.get('media') and m['media'] in media_map:
            mm['media'] = media_map[m['media']]
        if m.get('poster') and m['poster'] in media_map:
            mm['poster'] = media_map[m['poster']]
        c = m.get('content')
        if isinstance(c, dict) and c.get('records'):
            cc = dict(c)
            recs = []
            for r in c['records']:
                rr = dict(r)
                if r.get('media') and r['media'] in media_map:
                    rr['media'] = media_map[r['media']]
                recs.append(rr)
            cc['records'] = recs
            mm['content'] = cc
        out.append(mm)
    return out


def export_chats(store, targets, formats, since, until, out_dir,
                 archive=True, progress=None):
    """导出多个会话；archive=True 时每个会话生成自包含文件夹

    返回 {'files': [...], 'dir': 批次目录}
    """
    os.makedirs(out_dir, exist_ok=True)
    contacts = store.contacts()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    batch_dir = os.path.join(out_dir, f'导出_{stamp}') if archive else out_dir
    if archive:
        os.makedirs(batch_dir, exist_ok=True)
    files = []
    batch_chats = []
    total = max(1, len(targets))

    for idx, username in enumerate(targets, 1):
        msgs = store.messages(username, since=since, until=until)
        name = contacts.get(username, username)
        safe = re.sub(r'[\\/:*?"<>|]', '_', name)[:50] or '会话'
        if archive:
            chat_dir = _unique_dir(batch_dir, safe)
            os.makedirs(chat_dir, exist_ok=True)

            def cp_progress(p, msg):
                if progress:
                    overall = ((idx - 1) + p / 100 * 0.8) / total * 100
                    progress(int(overall), msg)
            media_map, counts = _collect_media(msgs, chat_dir, cp_progress)
            uri_fn = lambda p: media_map.get(p) or _default_uri(p)  # noqa: E731
            prefix = os.path.join(chat_dir, '聊天记录')
            html_path = os.path.join(chat_dir, 'index.html')
        else:
            chat_dir = None
            media_map, counts = {}, {}
            uri_fn = None
            prefix = os.path.join(batch_dir, f'{safe}_{stamp}')
            html_path = prefix + '.html'

        msgs_rel = _relativize(msgs, media_map) if archive else msgs
        chat_files = []

        if 'txt' in formats:
            p = prefix + '.txt'
            with open(p, 'w', encoding='utf-8') as f:
                f.write(f'{name} 聊天记录（{len(msgs)} 条）\n\n')
                for m in msgs:
                    f.write(f"[{m['time']}] {m['sender']}: {m['text']}\n")
            files.append(p)
            chat_files.append(p)
        if 'json' in formats:
            p = prefix + '.json'
            json.dump({'chat': name, 'username': username, 'count': len(msgs),
                       'messages': msgs_rel}, open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=2)
            files.append(p)
            chat_files.append(p)
        if 'csv' in formats:
            p = prefix + '.csv'
            with open(p, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.writer(f)
                w.writerow(['时间', '发送者', '类型', '内容', '媒体'])
                for m in msgs_rel:
                    w.writerow([m['time'], m['sender'], m['type'], m['text'],
                                m['media']])
            files.append(p)
            chat_files.append(p)
        if 'html' in formats:
            write_html(html_path, name, msgs, uri_fn)
            files.append(html_path)
            chat_files.append(html_path)

        if archive:
            manifest = {
                'chat': name,
                'username': username,
                'count': len(msgs),
                'since': since,
                'until': until,
                'exported_at': datetime.now().isoformat(timespec='seconds'),
                'media': counts,
                'files': [os.path.relpath(f, chat_dir).replace('\\', '/')
                          for f in chat_files],
            }
            with open(os.path.join(chat_dir, 'manifest.json'), 'w',
                      encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            batch_chats.append({'name': name, 'username': username,
                                'count': len(msgs),
                                'folder': os.path.basename(chat_dir)})

        if progress:
            progress(int(idx / total * 100), f'{name} 导出完成')

    if archive:
        with open(os.path.join(batch_dir, 'manifest.json'), 'w',
                  encoding='utf-8') as f:
            json.dump({'exported_at': datetime.now().isoformat(timespec='seconds'),
                       'chats': batch_chats}, f, ensure_ascii=False, indent=2)

    return {'files': files, 'dir': batch_dir}
