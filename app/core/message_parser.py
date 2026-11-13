# -*- coding: utf-8 -*-
"""微信消息内容解析

微信 4.x 的 local_type 为复合编码：高 32 位 = 子类型，低 32 位 = 基础类型。
基础类型 49 为 appmsg，子类型包括 57 引用、5 链接、6 文件、62 拍一拍等。

parse_content() 输出结构化字典，供导出与界面渲染使用：
  {kind, text, title, des, url, quote, file, app, amount, ...}
"""
import html as html_mod
import re
import xml.etree.ElementTree as ET

MEDIA_TEXT = {
    3: '[图片]', 34: '[语音]', 43: '[视频]', 47: '[表情]',
    48: '[位置]', 50: '[语音通话]', 42: '[名片]',
}


def split_local_type(lt):
    if not lt:
        return 0, 0
    return int(lt) & 0xFFFFFFFF, int(lt) >> 32


def _clean(s):
    if not s:
        return ''
    s = html_mod.unescape(s)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'[\t\r\n]+', ' ', s)
    s = re.sub(r'\s{2,}', ' ', s)
    return s.strip()


def _txt(root, tag):
    if root is None:
        return ''
    el = root.find(tag)
    if el is None:
        return ''
    return (el.text or '').strip()


def _fmt_size(n):
    try:
        n = int(n)
    except Exception:
        return ''
    if n <= 0:
        return ''
    if n < 1024:
        return f'{n} B'
    if n < 1024 * 1024:
        return f'{n / 1024:.1f} KB'
    if n < 1024 * 1024 * 1024:
        return f'{n / 1024 / 1024:.1f} MB'
    return f'{n / 1024 / 1024 / 1024:.2f} GB'


def _find_xml_start(s):
    i = s.find('<')
    return s[i:] if i > 0 else s


def _regex_field(raw, tag):
    m = re.search(rf'<{tag}>(.*?)</{tag}>', raw, re.S)
    if not m:
        return ''
    v = m.group(1)
    v = re.sub(r'^<!\[CDATA\[(.*)\]\]>$', r'\1', v.strip(), flags=re.S)
    return v


def _parse_xml(raw):
    """尽量宽容地解析 XML，失败返回 None"""
    s = _find_xml_start(raw.strip())
    try:
        return ET.fromstring(s)
    except ET.ParseError:
        fixed = re.sub(r'&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)', '&amp;', s)
        try:
            return ET.fromstring(fixed)
        except ET.ParseError:
            return None


def _quote_content(raw, qtype, depth=0):
    """引用原文：纯文本直接清洗；嵌套 XML 递归解析一层"""
    raw = (raw or '').strip()
    if not raw:
        return MEDIA_TEXT.get(qtype, '[消息]'), 'media'
    if raw.startswith('<') and depth < 2:
        sub = parse_content(qtype, raw, depth + 1)
        return sub.get('text') or sub.get('title') or '[消息]', sub.get('kind', 'text')
    return _clean(raw), 'text'


def _int(s, default=0):
    try:
        return int(str(s).strip())
    except Exception:
        return default


RECORD_KINDS = {
    1: 'text', 2: 'image', 3: 'voice', 4: 'video', 5: 'link',
    8: 'file', 17: 'link', 19: 'history', 37: 'sticker',
}
RECORD_PLACEHOLDER = {
    'text': '[文本]', 'image': '[图片]', 'voice': '[语音]', 'video': '[视频]',
    'file': '[文件]', 'link': '[链接]', 'history': '[聊天记录]', 'sticker': '[表情]',
}


def _parse_record(app):
    """解析转发聊天记录 <recorditem> 中的明细"""
    el = app.find('.//recorditem')
    if el is None:
        return []
    inner = (el.text or '').strip()
    if not inner:
        return []
    root = _parse_xml(inner)
    if root is None:
        return []
    dl = root.find('.//datalist')
    if dl is None:
        return []
    out = []
    for it in dl.findall('dataitem'):
        dt = _int(it.get('datatype'))
        kind = RECORD_KINDS.get(dt, 'unknown')
        sender = _clean(_txt(it, 'sourcename'))
        time_text = _clean(_txt(it, 'sourcetime'))
        title = _clean(_txt(it, 'datatitle'))
        desc = _clean(_txt(it, 'datadesc'))
        text = desc or title or RECORD_PLACEHOLDER.get(kind, '[消息]')
        out.append({
            'datatype': dt,
            'kind': kind,
            'sender': sender or '未知',
            'time': time_text,
            'text': text,
            'title': title,
            'md5': _clean(_txt(it, 'fullmd5')),
            'thumb_md5': _clean(_txt(it, 'thumbfullmd5')),
            'size': _fmt_size(_txt(it, 'datasize')),
        })
    return out


def _parse_appmsg(raw, sub_hint, depth=0):
    root = _parse_xml(raw)
    if root is None:
        # XML 损坏：退回正则提取 title/des/type
        title = _clean(_regex_field(raw, 'title') or _regex_field(raw, 'des'))
        return {'kind': 'app', 'text': f'[应用消息] {title}' if title else '[应用消息]',
                'title': title, 'des': '', 'url': ''}

    app = root.find('.//appmsg')
    if app is None:
        app = root if root.tag == 'appmsg' else root.find('appmsg')
    if app is None:
        text = _clean(raw)
        return {'kind': 'app', 'text': f'[应用消息] {text[:120]}', 'title': text[:120]}

    sub = _int(_txt(app, 'type'), sub_hint)
    title = _clean(_txt(app, 'title'))
    des = _clean(_txt(app, 'des'))
    url = _clean(_txt(app, 'url'))
    source = _clean(_txt(app, 'sourcedisplayname'))
    appname = _clean(_txt(app, 'appname')) or _clean(_txt(root, 'appinfo/appname'))

    # ---- 引用 ----
    if sub == 57:
        refer = app.find('refermsg')
        qname = _clean(_txt(refer, 'displayname'))
        qraw = _txt(refer, 'content')
        qtype = _int(_txt(refer, 'type'), 1)
        qtext, qkind = _quote_content(qraw, qtype, depth)
        if not qname:
            qname = '原消息'
        reply = title or '[引用消息]'
        summary = f'[引用] {reply[:60]}'
        if qtext:
            summary += f' ｜ 引用自 {qname}：{qtext[:60]}'
        return {
            'kind': 'quote',
            'text': summary,
            'reply': reply,
            'quote': {'sender': qname, 'text': qtext, 'kind': qkind},
        }

    # ---- 链接 ----
    if sub == 5:
        real_url = url or (title if title.startswith('http') else '')
        text = f'[链接] {title or real_url or des}'
        return {'kind': 'link', 'text': text, 'title': title,
                'des': des, 'url': real_url, 'source': source}

    # ---- 文件 ----
    if sub in (6, 74):
        attach = app.find('appattach')
        size = _fmt_size(_txt(attach, 'totallen')) if attach is not None else ''
        name = title or des or '[文件]'
        text = f'[文件] {name}' + (f' ({size})' if size else '')
        return {'kind': 'file', 'text': text, 'title': name,
                'size': size, 'url': url}

    # ---- 小程序 / 云文档 ----
    if sub in (33, 36):
        appname = source or des or ''
        text = f'[小程序] {title}' + (f' · {appname}' if appname else '')
        return {'kind': 'miniprogram', 'text': text, 'title': title,
                'des': des, 'app': appname, 'url': url}

    # ---- 音乐 ----
    if sub == 3:
        text = f'[音乐] {title}' + (f' - {des}' if des else '')
        return {'kind': 'music', 'text': text, 'title': title,
                'des': des, 'url': url, 'app': source}

    # ---- 视频分享 ----
    if sub == 4:
        text = f'[视频] {title}' + (f' · {des}' if des else '')
        return {'kind': 'video_share', 'text': text, 'title': title,
                'des': des, 'url': url, 'app': source}

    # ---- 聊天记录 ----
    if sub == 19:
        records = _parse_record(app)
        text = f'[聊天记录] {title}'
        if records:
            text += f' · {len(records)} 条'
        elif des:
            text += f' · {des[:60]}'
        return {'kind': 'chat_history', 'text': text, 'title': title,
                'des': des, 'url': url, 'records': records}

    # ---- 转账 / 红包 ----
    if sub == 2000:
        pay = app.find('wcpayinfo') or root.find('.//wcpayinfo')
        amount = _clean(_txt(pay, 'feedesc')) if pay is not None else ''
        text = f'[转账] {amount or title or des}'
        return {'kind': 'transfer', 'text': text, 'title': title,
                'des': des, 'amount': amount, 'url': url}
    if sub == 2001:
        text = f'[红包] {des or title or "微信红包"}'
        return {'kind': 'redpacket', 'text': text, 'title': title,
                'des': des, 'url': url}

    # ---- 拍一拍 ----
    if sub == 62:
        text = title or '拍了拍我'
        return {'kind': 'pat', 'text': text, 'title': text}

    # ---- 位置共享 ----
    if sub == 17:
        text = title or '[位置共享]'
        return {'kind': 'system', 'text': text, 'title': text}

    # ---- 接龙 ----
    if sub == 53:
        body = _clean(_txt(app, 'content'))
        text = title or body or '[接龙]'
        return {'kind': 'solitaire', 'text': text, 'title': title, 'des': body}

    # ---- 客服模板 ----
    if sub == 116:
        text = f'{title}' + (f' · {des}' if des else '')
        return {'kind': 'kf_template', 'text': text, 'title': title, 'des': des}

    # ---- 版本不支持 / 系统提示 ----
    if sub in (50, 51, 63, 87):
        text = title or des or '[该消息暂不支持展示]'
        return {'kind': 'unsupported', 'text': text, 'title': text}

    # ---- 其他应用消息：只取标题，绝不输出 XML ----
    text = title or des or '[应用消息]'
    if not text.startswith('['):
        text = f'[应用消息] {text}'
    return {'kind': 'app', 'text': text, 'title': title,
            'des': des, 'url': url, 'app': source}


def parse_content(local_type, raw, depth=0):
    """统一入口：返回结构化内容"""
    base, sub = split_local_type(local_type)
    raw = raw or ''

    if base == 1:
        return {'kind': 'text', 'text': raw}
    if base in (3, 34, 43, 47):
        return {'kind': {3: 'image', 34: 'voice', 43: 'video', 47: 'sticker'}[base],
                'text': MEDIA_TEXT.get(base, '[消息]')}
    if base == 42:
        return {'kind': 'card', 'text': '[名片]', 'title': _clean(raw)}
    if base == 48:
        s = _clean(raw)
        return {'kind': 'location', 'text': s or '[位置]', 'title': s}
    if base == 50:
        return {'kind': 'call', 'text': '[语音通话]'}
    if base in (10000, 10002):
        return {'kind': 'system', 'text': _clean(raw)}
    if base == 49:
        return _parse_appmsg(raw, sub, depth)

    # 未知基础类型：清理后展示，避免 XML 泄漏
    text = _clean(raw)
    return {'kind': 'text', 'text': text}
