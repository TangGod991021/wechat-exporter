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
from app.core.media import (build_video_index, default_workers,
                            load_video_index, prepare_video_playback)

TYPE_NAMES = {
    1: 'text', 3: 'image', 34: 'voice', 42: 'card', 43: 'video',
    47: 'sticker', 48: 'location', 49: 'app', 50: 'call',
    10000: 'system', 10002: 'system',
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
                 video_roots=None, video_cache='', video_playback_dir='',
                 ffmpeg='ffmpeg'):
        self.data_dir = data_dir
        self.images_dir = images_dir
        self.voices_dir = voices_dir
        self.my_wxid = my_wxid
        self.video_roots = video_roots or []
        self.video_cache = video_cache
        self.video_playback_dir = video_playback_dir
        self.ffmpeg = ffmpeg
        self.session_db = os.path.join(data_dir, 'session', 'session.db')
        self.contact_db = os.path.join(data_dir, 'contact', 'contact.db')
        self.media_db = os.path.join(data_dir, 'message', 'media_0.db')
        self.hardlink_db = os.path.join(data_dir, 'hardlink', 'hardlink.db')
        # 普通会话在 message_*.db；公众号（gh_*）在 biz_message_*.db。
        # 同一会话的消息表可能横跨多个分库（微信按时间/容量滚动写入），
        # 因此后续所有读取都要遍历全部命中的分库并合并。
        msg_dir = os.path.join(data_dir, 'message')
        self.message_dbs = sorted(glob.glob(os.path.join(msg_dir, 'message_*.db'))) + \
            sorted(glob.glob(os.path.join(msg_dir, 'biz_message_*.db')))
        self._names = None
        self._image_index = None
        self._image_suffix = None
        self._video_index = None
        self._table_map = None
        self._hardlink_names = None

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

    def table_map(self, progress=None):
        """建立「消息表名 -> 数据库路径列表」映射。

        同一张 Msg_<md5> 表可能同时出现在 message_0.db、message_1.db 等多个
        分库中（微信滚动分片）。旧实现用字典直接覆盖，只保留最后一个分库，
        导致导出只剩较新的那部分消息，必须保留全部命中分库。
        """
        if self._table_map is not None:
            return self._table_map
        mapping = {}
        total = max(1, len(self.message_dbs))
        for i, db in enumerate(self.message_dbs, 1):
            if progress:
                progress(int((i - 1) / total * 100),
                         f'正在读取消息库 {i}/{total}')
            try:
                c = sqlite3.connect(db)
                try:
                    rows = c.execute(
                        "select name from sqlite_master where type='table' "
                        "and name like 'Msg_%'").fetchall()
                finally:
                    c.close()
            except sqlite3.DatabaseError:
                continue  # 尚未解密或格式不符
            for (name,) in rows:
                mapping.setdefault(name, []).append(db)
        self._table_map = mapping
        if progress:
            progress(100, f'已读取 {total} 个消息库')
        return mapping

    def find_tables(self, username):
        """返回 (包含该会话消息表的全部分库列表, 表名)"""
        name = f"Msg_{hashlib.md5(username.encode()).hexdigest()}"
        return self.table_map().get(name, []), name

    def find_table(self, username):
        """兼容旧调用：返回第一个分库与表名"""
        dbs, name = self.find_tables(username)
        return (dbs[0], name) if dbs else (None, None)

    def message_count(self, username):
        """跨全部分库统计会话消息数"""
        dbs, table = self.find_tables(username)
        if not dbs:
            return 0
        total = 0
        for db in dbs:
            try:
                c = sqlite3.connect(db)
                try:
                    total += c.execute(
                        f'select count(*) from "{table}"').fetchone()[0]
                finally:
                    c.close()
            except sqlite3.DatabaseError:
                continue
        return total

    def table_counts(self, progress=None):
        """一次连接统计每个消息表的行数，并按库文件 mtime/size 缓存。

        旧实现为每个会话单独开连接执行 count(*)，会话多时首屏很慢；
        这里改为每个消息库只开一次连接，结果落盘缓存，重复进入会话页近乎瞬时。
        progress(pct, message) 用于向界面汇报进度。
        """
        def report(pct, msg=''):
            if progress:
                progress(int(max(0, min(100, pct))), msg)

        mapping = self.table_map(
            progress=(lambda p, m='': report(p * 0.15, m)) if progress else None)
        if not mapping:
            report(100, '没有找到消息表')
            return {}
        all_dbs = sorted({db for dbs in mapping.values() for db in dbs})
        sig = {}
        for db in all_dbs:
            try:
                st = os.stat(db)
                sig[os.path.basename(db)] = [st.st_mtime, st.st_size]
            except OSError:
                continue
        cache_path = os.path.join(self.data_dir, 'session_counts.json')
        # v2：旧版本只统计了单个分库，升级后必须重算，否则列表数量偏小
        cache_ver = 2
        if os.path.exists(cache_path):
            try:
                cached = json.load(open(cache_path, encoding='utf-8'))
                if (cached.get('v') == cache_ver and cached.get('sig') == sig):
                    report(100, '会话数量已缓存')
                    return cached.get('counts') or {}
            except (OSError, ValueError):
                pass

        by_db = {}
        for name, dbs in mapping.items():
            for db in dbs:
                by_db.setdefault(db, []).append(name)
        total_tables = sum(len(v) for v in by_db.values()) or 1
        counts = {}
        done = 0
        for db, names in by_db.items():
            try:
                c = sqlite3.connect(db)
                try:
                    for name in names:
                        try:
                            # 同名表可能分布在多个分库，数量必须累加
                            n = c.execute(
                                f'select count(*) from "{name}"').fetchone()[0]
                        except sqlite3.Error:
                            n = 0
                        counts[name] = counts.get(name, 0) + n
                        done += 1
                        report(15 + done / total_tables * 85,
                               f'正在统计会话消息数 {done}/{total_tables}')
                finally:
                    c.close()
            except sqlite3.DatabaseError:
                continue
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            tmp = cache_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump({'v': cache_ver, 'sig': sig, 'counts': counts}, fh)
            os.replace(tmp, cache_path)
        except OSError:
            pass
        return counts

    def sessions_with_counts(self, progress=None):
        def report(pct, msg=''):
            if progress:
                progress(int(max(0, min(100, pct))), msg)

        report(1, '正在读取会话与联系人...')
        items = self.sessions()
        report(3, f'找到 {len(items)} 个会话，正在统计消息数...')
        counts = self.table_counts(
            progress=(lambda p, m='': report(3 + p * 0.97, m))
            if progress else None)
        for it in items:
            table = f"Msg_{hashlib.md5(it['username'].encode()).hexdigest()}"
            it['count'] = counts.get(table, 0)
        report(100, f'会话列表加载完成（{len(items)} 个会话）')
        return items

    # ---------- 媒体 ----------
    def image_index(self):
        if self._image_index is None:
            best = {}
            self._image_suffix = {}
            if self.images_dir and os.path.isdir(self.images_dir):
                # 优先 _h（高清原图）：微信 4.x 的部分中间图是 WXAM/HEVC，
                # 首帧可能是白帧，直接转 JPG 会得到空白图片；_h 是完整原图。
                rank = {'_h': 0, '': 1, '_t': 2}
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
                        cur = best.get(key)
                        if cur is None or rank[suffix] < cur[0]:
                            best[key] = (rank[suffix], suffix,
                                         os.path.join(dirpath, n))
            self._image_index = {k: v[2] for k, v in best.items()}
            self._image_suffix = {k: v[1] for k, v in best.items()}
        return self._image_index

    def _find_image_info(self, md5):
        """返回 (路径, 质量后缀)；后缀为 _h / '' / _t，空串表示没有"""
        key = (md5 or '').lower()
        path = self.image_index().get(key)
        return path, (self._image_suffix or {}).get(key, '') if path else ''

    def _find_image(self, md5):
        return self.image_index().get((md5 or '').lower())

    def hardlink_stem(self, md5, kind='image'):
        """消息里的 md5 -> 本地素材文件名（不含扩展名）

        转发聊天记录里的图片/视频使用消息 md5，而本地缓存文件名是另一串
        哈希，必须经 hardlink.db 映射才能定位。
        """
        md5 = (md5 or '').lower()
        if not md5:
            return ''
        table = {'image': 'image_hardlink_info_v4',
                 'video': 'video_hardlink_info_v4',
                 'file': 'file_hardlink_info_v4'}.get(kind)
        if not table:
            return ''
        if self._hardlink_names is None:
            self._hardlink_names = {}
            if os.path.exists(self.hardlink_db):
                try:
                    c = sqlite3.connect(self.hardlink_db)
                    try:
                        for tbl in ('image_hardlink_info_v4',
                                    'video_hardlink_info_v4',
                                    'file_hardlink_info_v4'):
                            try:
                                rows = c.execute(
                                    f'select md5, file_name from "{tbl}"').fetchall()
                            except sqlite3.Error:
                                continue
                            for msg_md5, name in rows:
                                if not msg_md5 or not name:
                                    continue
                                # 图片/视频只取真实缓存文件名（部分行是内部 id）
                                low = name.lower()
                                if tbl == 'image_hardlink_info_v4' and not low.endswith('.dat'):
                                    continue
                                if tbl == 'video_hardlink_info_v4' and not low.endswith('.mp4'):
                                    continue
                                self._hardlink_names.setdefault(
                                    (tbl, msg_md5.lower()), name)
                    finally:
                        c.close()
                except sqlite3.Error:
                    pass
        name = self._hardlink_names.get((table, md5), '')
        if not name:
            return ''
        stem = os.path.splitext(name)[0]
        # 本地图片可能有 _h/_t 缩略/高清后缀，索引统一为无后缀名
        if stem[-2:].lower() in ('_h', '_t'):
            stem = stem[:-2]
        return stem

    def video_index(self):
        if self._video_index is None:
            if self.video_cache and os.path.exists(self.video_cache):
                self._video_index = load_video_index(self.video_cache)
            else:
                self._video_index = {}
        return self._video_index

    def refresh_video_index(self, progress=None):
        """按 mtime/size 增量更新视频索引，导出前调用以确保新视频可定位。"""
        if not self.video_roots:
            self._video_index = {}
            return {}
        self._video_index = build_video_index(
            self.video_roots, self.video_cache, progress=progress)
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
    def messages(self, username, since=None, until=None, limit=None,
                 before_ts=None, before_id=None, before_sort=None):
        """读取会话消息（遍历该会话所在的全部分库并合并）。

        微信 4.x 会把同一会话的消息表滚动写入 message_0.db、message_1.db …
        等多个分库；只读其中一个库会丢失大量历史消息。这里逐库查询后按
        (create_time, sort_seq, local_id) 合并排序，分页游标也一并支持
        sort_seq（同一秒内的毫秒级顺序）。
        """
        dbs, table = self.find_tables(username)
        if not dbs:
            return []
        conds, params = [], []
        if since:
            conds.append('create_time >= ?')
            params.append(int(datetime.strptime(since, '%Y-%m-%d').timestamp()))
        if until:
            conds.append('create_time <= ?')
            params.append(int(datetime.strptime(until, '%Y-%m-%d').timestamp()) + 86399)
        base_conds, base_params = list(conds), list(params)

        contacts = self.contacts()
        merged = {}
        for db in dbs:
            try:
                c = sqlite3.connect(db)
                try:
                    # Name2Id 只在各自分库内有效，发送人映射必须按库建立
                    names = {rid: u for rid, u in
                             c.execute('select rowid, user_name from Name2Id')}
                    try:
                        cols = {r[1] for r in
                                c.execute(f'pragma table_info("{table}")')}
                    except sqlite3.DatabaseError:
                        cols = set()
                    has_sort = 'sort_seq' in cols
                    db_conds, db_params = list(base_conds), list(base_params)
                    if before_ts is not None:
                        if before_sort is not None and has_sort:
                            # 优先使用毫秒序号；同一毫秒再按 local_id 兜底
                            db_conds.append(
                                '(create_time < ? or '
                                '(create_time = ? and sort_seq < ?) or '
                                '(create_time = ? and sort_seq = ? and local_id < ?))')
                            db_params += [int(before_ts), int(before_ts),
                                          int(before_sort), int(before_ts),
                                          int(before_sort), int(before_id or 0)]
                        elif before_id is not None:
                            # 旧游标：同一秒内的消息按 local_id 继续向下翻
                            db_conds.append('(create_time < ? or '
                                            '(create_time = ? and local_id < ?))')
                            db_params += [int(before_ts), int(before_ts),
                                          int(before_id)]
                        else:
                            db_conds.append('create_time < ?')
                            db_params.append(int(before_ts))
                    where = ('where ' + ' and '.join(db_conds)) if db_conds else ''
                    sort_col = 'sort_seq' if has_sort else '0'
                    sql = (f'select local_id, local_type, real_sender_id, create_time, '
                           f'message_content, packed_info_data, {sort_col} '
                           f'from "{table}" {where} order by create_time desc, '
                           + ('sort_seq desc, ' if has_sort else '')
                           + 'local_id desc')
                    if limit:
                        sql += f' limit {int(limit)}'
                    rows = c.execute(sql, db_params).fetchall()
                finally:
                    c.close()
            except sqlite3.DatabaseError:
                continue  # 单个分库异常不影响其它分库
            for local_id, ltype, sender_id, ctime, content, packed, sort_seq in rows:
                # 分库迁移/重复写入时可能拿到同一条消息，按完整行去重
                key = (ctime, sort_seq or 0, local_id, sender_id or 0, content)
                if key in merged:
                    continue
                m = self._parse(username, names, contacts,
                                (local_id, ltype, sender_id, ctime, content, packed))
                m['sort_seq'] = sort_seq or 0
                merged[key] = m

        items = sorted(merged.items(),
                       key=lambda kv: (kv[0][0], kv[0][1], kv[0][2]),
                       reverse=True)
        if limit:
            items = items[:int(limit)]
        out = [m for _key, m in items]
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

        # 群聊消息常带 "发送者wxid:\n" 前缀；按真实 sender 精确剥离，
        # 既支持自定义微信号，也避免 XML 类型因前缀解析失败
        if sender:
            for prefix in (sender + ':\r\n', sender + ':\n'):
                if content.startswith(prefix):
                    content = content[len(prefix):]
                    break

        parsed = parse_content(ltype, content)
        kind = parsed.get('kind', 'text')
        text = parsed.get('text', '')
        media = ''
        poster = ''
        video_md5 = ''
        image_md5 = ''

        if kind == 'chat_history':
            for rec in parsed.get('records', []):
                md5 = rec.get('md5') or rec.get('thumb_md5')
                if rec.get('kind') == 'video':
                    rec['media'] = self._find_video(md5) or ''
                    rec['video_md5'] = md5 or ''
                elif rec.get('kind') == 'image':
                    stem = self.hardlink_stem(md5, 'image') or (md5 or '')
                    rec['media'] = self._find_image(stem) or ''
                    rec['image_md5'] = stem
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
            image_md5 = (md5 or '').lower()
            media = self._find_image(md5) or ''
        elif base == 34:
            m = re.search(r'voicelength="(\d+)"', content)
            secs = int(m.group(1)) / 1000 if m else 0
            # 语音按 username（wxid/@chatroom）分目录，不能用备注/昵称
            media = self._find_voice(chat, local_id) or ''
            text = f'[语音 {secs:.0f}s]' if secs else '[语音]'
        elif base == 43:
            m = re.search(r'md5="([0-9a-fA-F]{32})"', content)
            md5 = m.group(1).lower() if m else None
            video_md5 = md5 or ''
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
            'video_md5': video_md5,
            'image_md5': image_md5,
            'content': parsed,
        }


URL_RE = re.compile(r'(https?://[^\s<"]+)')
SAFE_HREF_RE = re.compile(r'^(https?://|mailto:)', re.I)


def _safe_href(url):
    """只允许 http/https/mailto，阻止 javascript: / data: 等可执行 scheme"""
    url = (url or '').strip()
    return url if SAFE_HREF_RE.match(url) else ''


def linkify(s):
    """先转义再识别链接，避免注入"""
    esc = html.escape(s or '')
    return URL_RE.sub(
        lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener noreferrer">{m.group(1)}</a>',
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
            if not uri:
                media_html = '<span class="missing">[媒体缺失]</span>'
            elif low.endswith('.mp4'):
                media_html = f'<video class="ri-img" controls src="{uri}"></video>'
            elif low.endswith('.wav'):
                media_html = f'<audio controls src="{uri}"></audio>'
            else:
                media_html = (f'<img class="ri-img" src="{uri}" loading="lazy" '
                              f'title="点击放大">')
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
        href = _safe_href(c.get('url'))
        title_html = (f'<a href="{html.escape(href)}" target="_blank" rel="noopener noreferrer">'
                      f'{linkify(c.get("title") or href)}</a>') if href else linkify(c.get('title', ''))
        des = f'<div class="card-des">{linkify(c.get("des", ""))}</div>' if c.get('des') else ''
        meta = f'<div class="card-meta">{html.escape(_domain(href))}</div>' if href else ''
        return f'<div class="card"><div class="card-title">{title_html}</div>{des}{meta}</div>'
    if kind == 'file':
        meta = f'<div class="card-meta">{html.escape(c.get("size", ""))}</div>' if c.get('size') else ''
        return (f'<div class="card"><div class="card-title">📄 '
                f'{html.escape(c.get("title", m.get("text", "")))}</div>{meta}</div>')
    if kind == 'location':
        href = _safe_href(c.get('url'))
        title = html.escape(c.get('title') or m.get('text', ''))
        if href:
            title = (f'<a href="{html.escape(href)}" target="_blank" '
                     f'rel="noopener noreferrer">{title}</a>')
        des = (f'<div class="card-meta">{html.escape(c.get("des", ""))}</div>'
               if c.get('des') else '')
        return f'<div class="card"><div class="card-title">📍 {title}</div>{des}</div>'
    if kind in ('miniprogram', 'music', 'video_share', 'chat_history',
                'transfer', 'redpacket', 'kf_template', 'app', 'card',
                'announcement'):
        icon = {'miniprogram': '🧩', 'music': '🎵', 'video_share': '🎬',
                'chat_history': '💬', 'transfer': '💰', 'redpacket': '🧧',
                'kf_template': '📢', 'app': '📦', 'card': '👤',
                'announcement': '📢'}.get(kind, '📦')
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
box-shadow:0 1px 3px rgba(0,0,0,.06);white-space:pre-wrap;word-break:break-word;line-height:1.6}}
.missing{{color:#c33;font-size:12px}}
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
img.chat-img,img.ri-img{{cursor:zoom-in}}
#lightbox{{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;
align-items:center;justify-content:center;z-index:9999;padding:24px;cursor:zoom-out}}
#lightbox.show{{display:flex}}
#lightbox img{{max-width:92vw;max-height:92vh;border-radius:8px;
box-shadow:0 20px 60px rgba(0,0,0,.5);object-fit:contain;background:#fff}}
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
            if not uri:
                body += '<br><span class="missing">[媒体缺失]</span>'
            elif low.endswith('.wav'):
                body += f'<br><audio controls src="{uri}"></audio>'
            elif low.endswith('.mp4'):
                poster = uri_fn(m['poster']) if m.get('poster') else ''
                poster_attr = f' poster="{poster}"' if poster else ''
                body += (f'<br><video class="chat-video" controls{poster_attr} '
                         f'src="{uri}"></video>')
            else:
                body += (f'<br><img class="chat-img" src="{uri}" loading="lazy" '
                         f'title="点击放大">')
        parts.append(
            f'<div class="{cls}"><div class="meta">{esc(m["sender"])} · {esc(m["time"])}</div>'
            f'<div class="bubble">{body}</div></div>')
    parts.append("""<div id="lightbox" role="dialog" aria-label="图片预览"><img alt="图片预览"></div>
<script>
(function(){
  var lb=document.getElementById('lightbox'),big=lb&&lb.querySelector('img');
  function close(){lb.classList.remove('show');big.removeAttribute('src');document.body.style.overflow='';}
  document.addEventListener('click',function(e){
    var t=e.target;
    if(t&&t.tagName==='IMG'&&(t.classList.contains('chat-img')||t.classList.contains('ri-img'))){
      big.src=t.currentSrc||t.src;lb.classList.add('show');document.body.style.overflow='hidden';
    }else if(e.target===lb||e.target===big){close();}
  });
  document.addEventListener('keydown',function(e){if(e.key==='Escape')close();});
})();
</script>
</body></html>""")
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
    missing = []
    counts = {'images': 0, 'videos': 0, 'audio': 0, 'files': 0}
    total = len(tasks)
    for i, (src, ts) in enumerate(tasks, 1):
        if not src or src in media_map:
            continue
        if not os.path.exists(src):
            missing.append(src)
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
            missing.append(src)
            continue
        media_map[src] = f'{kind}/{os.path.basename(dest)}'
        counts[kind] = counts.get(kind, 0) + 1
        if progress and i % 20 == 0:
            progress(int(i / total * 100) if total else 100, f'复制媒体 {i}/{total}')
    return media_map, counts, missing


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


def _video_md5s(msgs):
    """收集消息中被引用的视频 md5（含转发聊天记录里的视频）。"""
    found = set()
    for m in msgs:
        if m.get('video_md5'):
            found.add(m['video_md5'])
        for r in (m.get('content') or {}).get('records') or []:
            if r.get('video_md5'):
                found.add(r['video_md5'])
    return found


def collect_media_ids(store, targets, progress=None):
    """解析所选会话，收集需要处理的图片 / 语音 / 视频标识。"""
    images, voices, videos = set(), set(), set()
    total = max(1, len(targets))
    for i, username in enumerate(targets, 1):
        for m in store.messages(username):
            if m.get('image_md5'):
                images.add(m['image_md5'].lower())
            if m.get('video_md5'):
                videos.add(m['video_md5'].lower())
            if m.get('type') == 'voice' or m.get('kind') == 'voice':
                voices.add((username, m['local_id']))
            for r in (m.get('content') or {}).get('records') or []:
                if r.get('kind') == 'image':
                    for key in ('md5', 'thumb_md5', 'image_md5'):
                        v = (r.get(key) or '').lower()
                        if v:
                            images.add(v)
                if r.get('video_md5'):
                    videos.add(r['video_md5'].lower())
        if progress:
            progress(int(i / total * 100), f'解析所选会话 {i}/{total}')
    return {'images': images, 'voices': voices, 'videos': videos}


def _apply_playback(msgs, playback_dir):
    """转码完成后，把消息里的视频路径指向 H.264 缓存文件。"""
    def patched(md5):
        p = os.path.join(playback_dir, md5 + '.mp4')
        return p if os.path.exists(p) else ''

    for m in msgs:
        if m.get('video_md5'):
            p = patched(m['video_md5'])
            if p:
                m['media'] = p
        for r in (m.get('content') or {}).get('records') or []:
            if r.get('video_md5'):
                p = patched(r['video_md5'])
                if p:
                    r['media'] = p


WINDOWS_RESERVED = {'con', 'prn', 'aux', 'nul'} |     {f'com{i}' for i in range(1, 10)} | {f'lpt{i}' for i in range(1, 10)}


def _safe_name(name):
    """Windows 合法文件名：替换非法字符、去尾点空格、避开保留设备名"""
    s = re.sub(r'[\\/:*?"<>|]', '_', name or '').strip().rstrip('. ')
    s = s[:50] or '会话'
    if s.lower() in WINDOWS_RESERVED:
        s = '_' + s
    return s


def export_chats(store, targets, formats, since, until, out_dir,
                 archive=True, progress=None):
    """导出多个会话；archive=True 时每个会话生成自包含文件夹

    单个会话失败不会中断整批：错误写入返回值的 errors 与批次 manifest。
    """
    os.makedirs(out_dir, exist_ok=True)
    contacts = store.contacts()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    batch_dir = os.path.join(out_dir, f'导出_{stamp}') if archive else out_dir
    if archive:
        os.makedirs(batch_dir, exist_ok=True)
    files = []
    batch_chats = []
    errors = []
    total = max(1, len(targets))

    def export_one(idx, username):
        msgs = store.messages(username, since=since, until=until)

        # 只转码本次导出涉及的视频（HEVC -> H.264），不再全量预处理
        tc_share = 0.0
        md5s = _video_md5s(msgs)
        if md5s and store.video_playback_dir:
            video_idx = {md5: src for md5, src in store.video_index().items()
                         if md5 in md5s}
            if video_idx:
                tc_share = 0.3

                def tc_progress(p, msg, _no=idx):
                    if progress:
                        overall = ((_no - 1) + p / 100 * tc_share) / total * 100
                        progress(int(overall), msg)

                prepare_video_playback(
                    video_idx, store.video_cache, store.video_playback_dir,
                    store.ffmpeg, workers=default_workers(),
                    progress=tc_progress, only_md5s=md5s)
                _apply_playback(msgs, store.video_playback_dir)

        name = contacts.get(username, username)
        safe = _safe_name(name)
        if archive:
            chat_dir = _unique_dir(batch_dir, safe)
            os.makedirs(chat_dir, exist_ok=True)

            def cp_progress(p, msg):
                if progress:
                    overall = ((idx - 1) + tc_share
                               + p / 100 * (0.8 - tc_share)) / total * 100
                    progress(int(overall), msg)
            media_map, counts, missing = _collect_media(msgs, chat_dir, cp_progress)
            # 归档模式不再回退绝对 file:///：缺失媒体在 HTML 中标记出来
            uri_fn = lambda p: media_map.get(p) or ''  # noqa: E731
            prefix = os.path.join(chat_dir, '聊天记录')
            html_path = os.path.join(chat_dir, 'index.html')
        else:
            chat_dir = None
            media_map, counts = {}, {}
            uri_fn = None
            # 平铺模式附 username 摘要，避免同名会话互相覆盖
            tag = hashlib.md5(username.encode()).hexdigest()[:6]
            prefix = os.path.join(batch_dir, f'{safe}_{stamp}_{tag}')
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
                'missing_media': missing,
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

    for idx, username in enumerate(targets, 1):
        try:
            export_one(idx, username)
        except Exception as e:  # noqa: BLE001
            name = contacts.get(username, username)
            errors.append({'username': username, 'name': name,
                           'error': f'{type(e).__name__}: {e}'})
            if progress:
                progress(int(idx / total * 100), f'{name} 导出失败：{e}')

    if archive:
        with open(os.path.join(batch_dir, 'manifest.json'), 'w',
                  encoding='utf-8') as f:
            json.dump({'exported_at': datetime.now().isoformat(timespec='seconds'),
                       'chats': batch_chats, 'errors': errors},
                      f, ensure_ascii=False, indent=2)

    return {'files': files, 'dir': batch_dir, 'errors': errors}
