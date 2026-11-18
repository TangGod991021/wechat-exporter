# -*- coding: utf-8 -*-
"""微信本地附件定位

文件类消息（appmsg type 6/74）的 XML 里只有文件名和大小，没有 md5。
微信把收到的文件放在：
  <账号>/msg/file/<YYYY-MM>/<文件名>
  <账号>/msg/attach/<会话hash>/<YYYY-MM>/Rec/.../F/<n>/<文件名>
另外 hardlink.db 的 file_hardlink_info_v4 维护 md5 -> 本地文件名，
可用于转发聊天记录里的文件（记录项带 fullmd5）。
"""
import html
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

_MONTH_RE = re.compile(r'^(19|20)\d{2}-(0[1-9]|1[0-2])$')
_SUFFIX_RE = re.compile(r'\s*\(\d+\)$')
_SKIP_EXTS = ('.dat', '.tmp', '.part')


@dataclass
class FileEntry:
    path: str
    name: str
    size: int
    mtime: float
    month: str


def normalize_name(name: str) -> str:
    return (html.unescape(name or '')).replace(' ', ' ').strip()


def base_name(name: str) -> str:
    """去掉 Windows 重名后缀：工作交接.md (1).zip -> 工作交接.md.zip"""
    name = normalize_name(name)
    stem, ext = os.path.splitext(name)
    stem = _SUFFIX_RE.sub('', stem)
    return (stem + ext).strip()


def _month_of(path: str) -> str:
    for part in path.replace('/', '\\').split('\\'):
        if _MONTH_RE.match(part):
            return part
    return ''


_ATTACH_SKIP_DIRS = {'img', 'v', 'video', 'thumb', 'audio', 'emoji',
                     'emoticon', 'voice', 'temp', 'cache'}


def _iter_files(root: str):
    if not root or not os.path.isdir(root):
        return
    is_file_root = os.path.basename(os.path.normpath(root)).lower() == 'file'
    for dirpath, dirs, names in os.walk(root):
        if not is_file_root:
            # attach 目录只关心 F（文件）分支，跳过图片/视频等媒体目录
            dirs[:] = [d for d in dirs if d.lower() not in _ATTACH_SKIP_DIRS]
            rel = os.path.relpath(dirpath, root)
            parts = [p.lower() for p in rel.split(os.sep)] if rel != '.' else []
            if 'f' not in parts:
                continue
        for name in names:
            low = name.lower()
            if low.endswith(_SKIP_EXTS):
                continue
            p = os.path.join(dirpath, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if not os.path.isfile(p) or st.st_size <= 0:
                continue
            yield FileEntry(path=p, name=name, size=st.st_size,
                            mtime=st.st_mtime, month=_month_of(p))


class FileIndex:
    """按文件名、大小、月份定位本地附件"""

    def __init__(self, file_dir: str, attach_dir: str, hardlink_db: str = ''):
        self.file_dir = file_dir
        self.attach_dir = attach_dir
        self.hardlink_db = hardlink_db
        self._by_name = None
        self._by_base = None
        self._md5_names = None

    def _build(self):
        if self._by_name is not None:
            return
        by_name, by_base = {}, {}
        for root in (self.file_dir, self.attach_dir):
            for ent in _iter_files(root):
                by_name.setdefault(ent.name, []).append(ent)
                by_base.setdefault(base_name(ent.name), []).append(ent)
        self._by_name = by_name
        self._by_base = by_base

    def candidates(self, name: str):
        self._build()
        name = normalize_name(name)
        if not name:
            return []
        # 同名文件可能带 (1)(2) 等重名后缀，精确名和去后缀名都要参与比较
        out, seen = [], set()
        for ent in (self._by_name.get(name, [])
                    + self._by_base.get(base_name(name), [])):
            if ent.path not in seen:
                seen.add(ent.path)
                out.append(ent)
        return out

    def find(self, name: str, size: int = 0, ts: int = 0):
        """返回最匹配的 FileEntry，找不到返回 None。

        精确文件名优先；同名多版本再按大小、月份、mtime 接近程度选择。
        """
        cands = self.candidates(name)
        if not cands:
            return None
        name = normalize_name(name)
        month = ''
        if ts:
            try:
                month = datetime.fromtimestamp(ts).strftime('%Y-%m')
            except (OSError, ValueError):
                month = ''
        size = int(size or 0)

        def score(ent):
            return (0 if ent.name == name else 1,
                    0 if size and ent.size == size else 1,
                    0 if month and ent.month == month else 1,
                    abs(ent.mtime - ts) if ts else 0)
        return min(cands, key=score)

    # ---------- 转发记录：按 md5 映射 ----------
    def _load_md5_names(self):
        if self._md5_names is not None:
            return
        self._md5_names = {}
        if not self.hardlink_db or not os.path.exists(self.hardlink_db):
            return
        try:
            c = sqlite3.connect(self.hardlink_db)
            try:
                rows = c.execute(
                    'select md5, file_name from file_hardlink_info_v4').fetchall()
            finally:
                c.close()
        except sqlite3.Error:
            return
        for md5, name in rows:
            if md5 and name:
                self._md5_names.setdefault(md5.lower(), []).append(name)

    def find_md5(self, md5: str, size: int = 0, ts: int = 0):
        """按 hardlink 记录的本地文件名精确查找。

        文件名不存在说明文件已被微信清理，不能退回到同名不同版本的文件，
        否则会把内容不对的附件当成命中的结果。
        """
        md5 = (md5 or '').lower()
        if not md5:
            return None
        self._load_md5_names()
        self._build()
        for name in self._md5_names.get(md5, []):
            cands = self._by_name.get(name, [])
            if not cands:
                continue
            size = int(size or 0)
            month = ''
            if ts:
                try:
                    month = datetime.fromtimestamp(ts).strftime('%Y-%m')
                except (OSError, ValueError):
                    month = ''
            return min(cands, key=lambda e: (
                0 if size and e.size == size else 1,
                0 if month and e.month == month else 1,
                abs(e.mtime - ts) if ts else 0))
        return None
