# -*- coding: utf-8 -*-
"""媒体处理：图片 V2 解密 / WxAM→JPG / 语音 SILK→WAV

优化点：
  1. 增量：已存在且源文件未变化的产物直接跳过
  2. 分块进程池：绕开 GIL，减少任务分发开销
  3. WxAM 优先用 PyAV 进程内解码，失败回退 ffmpeg
  4. 图片与语音并发执行，HEVC 在图片完成后接续
"""
import glob
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import struct
from app.core import proc
import tempfile
import threading
import wave
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime

from Crypto.Cipher import AES
from Crypto.Util import Padding

MAGIC_V2 = b'\x07\x08V2\x08\x07'
IMAGE_EXTS = ('.jpg', '.png', '.webp', '.gif')
CHUNK_FILES = 500


# ---------------------------------------------------------------- 工具
def _detect(data):
    if data[:3] == b'\xff\xd8\xff':
        return '.jpg'
    if data[:4] == bytes([0x89, 0x50, 0x4E, 0x47]):
        return '.png'
    if data[:4] == b'RIFF':
        return '.webp'
    if data[:4] == b'wxgf':
        return '.hevc'
    if data[:3] == b'GIF':
        return '.gif'
    return '.bin'


def default_workers():
    cpu = os.cpu_count() or 4
    return max(2, min(8, cpu - 1))


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _existing_outputs(outdir):
    """stem -> path，用于增量判断"""
    out = {}
    try:
        for name in os.listdir(outdir):
            stem, ext = os.path.splitext(name)
            if ext.lower() in IMAGE_EXTS:
                out.setdefault(stem, os.path.join(outdir, name))
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- 图片密钥
def image_key_candidates(wxid, codes):
    out = []
    for code in codes:
        aes_key = hashlib.md5((code + wxid).encode()).hexdigest()[:16].encode()
        out.append((code, aes_key, int(code) & 0xFF))
    return out


def derive_image_key(attach_dir, wxid, codes):
    sample = None
    for f in glob.glob(os.path.join(attach_dir, '*', '*', 'Img', '*.dat')):
        try:
            with open(f, 'rb') as fh:
                head = fh.read(31)
            if head[:6] == MAGIC_V2:
                sample = head[15:31]
                break
        except OSError:
            continue
    if not sample:
        return None
    for code, aes_key, xor_key in image_key_candidates(wxid, codes):
        try:
            plain = AES.new(aes_key, AES.MODE_ECB).decrypt(sample)
            if _detect(plain) in IMAGE_EXTS or plain[:4] == b'wxgf':
                return code, aes_key.decode(), xor_key
        except Exception:
            continue
    return None


def decode_dat(path, aes_key_hex, xor_key, cipher=None):
    with open(path, 'rb') as f:
        data = f.read()
    if data[:6] == MAGIC_V2:
        aes_size, xor_size = struct.unpack_from('<LL', data, 6)
        aligned = (aes_size // 16 + 1) * 16
        if 15 + aligned > len(data):
            aligned = aes_size + (-aes_size % 16)
        enc = data[15:15 + aligned]
        c = cipher or AES.new(aes_key_hex.encode(), AES.MODE_ECB)
        dec = c.decrypt(enc)
        try:
            dec = Padding.unpad(dec, AES.block_size)
        except ValueError:
            pass
        raw = data[15 + aligned:len(data) - xor_size]
        tail = data[len(data) - xor_size:]
        return dec + raw + bytes(b ^ xor_key for b in tail)
    return bytes(b ^ xor_key for b in data)


# ---------------------------------------------------------------- 进程池 worker（必须顶层）
def _image_batch_worker(args):
    batch, aes_key_hex, xor_key = args
    cipher = AES.new(aes_key_hex.encode(), AES.MODE_ECB)
    ok = fail = 0
    formats = {}
    for src, outdir in batch:
        try:
            plain = decode_dat(src, aes_key_hex, xor_key, cipher)
            ext = _detect(plain)
            os.makedirs(outdir, exist_ok=True)
            dst = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ext)
            with open(dst, 'wb') as f:
                f.write(plain)
            ok += 1
            formats[ext] = formats.get(ext, 0) + 1
        except Exception:
            fail += 1
    return ok, fail, formats


def _wxam_batch_worker(batch):
    """batch: [(hevc_path, jpg_path)]，优先 PyAV，失败回退 ffmpeg"""
    try:
        import av
        use_av = True
    except Exception:
        av = None
        use_av = False
    ok = fail = 0
    for src, dst in batch:
        done = False
        try:
            with open(src, 'rb') as f:
                data = f.read()
            pos = data.find(b'\x00\x00\x00\x01')
            if pos >= 0 and use_av:
                container = av.open(io.BytesIO(data[pos:]), format='hevc')
                frame = next(container.decode(video=0))
                img = frame.to_image()
                img.save(dst, 'JPEG', quality=92)
                container.close()
                done = True
        except Exception:
            done = False
        if not done:
            try:
                with open(src, 'rb') as f:
                    data = f.read()
                pos = data.find(b'\x00\x00\x00\x01')
                if pos < 0:
                    fail += 1
                    continue
                fd, tmp = tempfile.mkstemp(suffix='.hevc')
                os.close(fd)
                with open(tmp, 'wb') as f:
                    f.write(data[pos:])
                r = proc.run(
                    ['ffmpeg', '-y', '-v', 'error', '-f', 'hevc', '-i', tmp,
                     '-frames:v', '1', '-q:v', '2', dst],
                    capture_output=True, timeout=60)
                os.remove(tmp)
                done = r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0
            except Exception:
                done = False
        if done:
            ok += 1
        else:
            fail += 1
            if os.path.exists(dst):
                try:
                    os.remove(dst)
                except OSError:
                    pass
    return ok, fail


def _voice_batch_worker(batch):
    """batch: [(out_path, silk_bytes)]"""
    import pilk
    tmpdir = tempfile.mkdtemp(prefix='silk_')
    silk_p = os.path.join(tmpdir, 'a.silk')
    pcm_p = os.path.join(tmpdir, 'a.pcm')
    ok = fail = 0
    for out_path, blob in batch:
        try:
            silk = blob[1:] if blob[:1] == b'\x02' else blob
            if not silk.startswith(b'#!SILK_V3'):
                fail += 1
                continue
            with open(silk_p, 'wb') as f:
                f.write(silk)
            pilk.decode(silk_p, pcm_p, 24000)
            pcm = open(pcm_p, 'rb').read()
            if not pcm:
                fail += 1
                continue
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with wave.open(out_path, 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm)
            ok += 1
        except Exception:
            fail += 1
    shutil.rmtree(tmpdir, ignore_errors=True)
    return ok, fail


# ---------------------------------------------------------------- 各阶段
def _plan_images(attach_dir, out_dir):
    pending, skipped = [], 0
    dirs = {}
    for dirpath, _dirs, names in os.walk(attach_dir):
        if os.path.basename(dirpath) != 'Img':
            continue
        rel = os.path.relpath(dirpath, attach_dir)
        outdir = os.path.join(out_dir, rel)
        existing = _existing_outputs(outdir)
        for n in names:
            if not n.endswith('.dat'):
                continue
            src = os.path.join(dirpath, n)
            stem = os.path.splitext(n)[0]
            out = existing.get(stem)
            if out and os.path.getmtime(out) >= os.path.getmtime(src):
                skipped += 1
                continue
            pending.append((src, outdir))
    return pending, skipped


def _plan_wxam(images_dir):
    pending, skipped = [], 0
    for dirpath, _dirs, names in os.walk(images_dir):
        for n in names:
            if not n.lower().endswith('.hevc'):
                continue
            src = os.path.join(dirpath, n)
            dst = os.path.splitext(src)[0] + '.jpg'
            if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
                skipped += 1
                continue
            pending.append((src, dst))
    return pending, skipped


def build_video_index(video_roots, cache_path, progress=None):
    """为本地 mp4 建立「明文 md5 -> 路径」索引（持久化，按 mtime/size 增量）

    微信视频文件名是随机哈希，但消息 XML 的 md5 属性等于加密前文件的 MD5，
    因此需要计算本地文件 md5 才能完成映射。
    """
    cache = {}
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding='utf-8'))
        except Exception:
            cache = {}
    files = []
    for root in video_roots or []:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, names in os.walk(root):
            for n in names:
                if n.lower().endswith('.mp4'):
                    files.append(os.path.join(dirpath, n))
    index = {}
    for i, f in enumerate(files, 1):
        try:
            st = os.stat(f)
        except OSError:
            continue
        ent = cache.get(f)
        if ent and ent.get('mtime') == st.st_mtime and ent.get('size') == st.st_size:
            md5 = ent['md5']
        else:
            try:
                md5 = hashlib.md5(open(f, 'rb').read()).hexdigest()
            except OSError:
                continue
            cache[f] = {'mtime': st.st_mtime, 'size': st.st_size, 'md5': md5}
        index[md5] = f
        if progress and i % 20 == 0:
            progress(int(i / len(files) * 100))
    if cache_path:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            tmp = cache_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(cache, fh, ensure_ascii=False)
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return index


def load_video_index(cache_path):
    """从缓存构建 md5 -> path（不重新计算）"""
    try:
        data = json.load(open(cache_path, encoding='utf-8'))
    except Exception:
        return {}
    return {v['md5']: k for k, v in data.items()
            if v.get('md5') and os.path.exists(k)}


def _probe_codec(ffmpeg, path):
    ffprobe = 'ffprobe'
    d = os.path.dirname(ffmpeg) if ffmpeg else ''
    if d and os.path.exists(os.path.join(d, 'ffprobe.exe')):
        ffprobe = os.path.join(d, 'ffprobe.exe')
    try:
        r = proc.run(
            [ffprobe, '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=20)
        return (r.stdout or '').strip().lower()
    except Exception:
        return ''


def _transcode_one(src, dst, ffmpeg):
    tmp = dst + '.tmp.mp4'
    try:
        r = proc.run(
            [ffmpeg, '-y', '-v', 'error', '-i', src,
             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
             '-c:a', 'aac', '-movflags', '+faststart', tmp],
            capture_output=True, timeout=600)
        if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, dst)
            return True
    except Exception:
        pass
    if os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
    return False


def prepare_video_playback(video_index, cache_path, playback_dir, ffmpeg='ffmpeg',
                           workers=4, progress=None, only_md5s=None):
    """把 HEVC 视频转码为 H.264 缓存，保证浏览器/WebView 可播放

    only_md5s 非空时只处理指定视频（导出时按所选会话过滤）。
    codec 结果写回 video_index.json，避免每次重新探测。
    """
    os.makedirs(playback_dir, exist_ok=True)
    cache = {}
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding='utf-8'))
        except Exception:
            cache = {}
    by_md5 = {v['md5']: k for k, v in cache.items() if v.get('md5')}
    codecs = {v['md5']: v.get('codec', '') for v in cache.values() if v.get('md5')}

    hevc_tasks = []
    hevc = skipped = selected = 0
    for md5, src in video_index.items():
        if only_md5s is not None and md5 not in only_md5s:
            continue
        selected += 1
        codec = codecs.get(md5)
        if not codec:
            codec = _probe_codec(ffmpeg, src)
            codecs[md5] = codec
            p = by_md5.get(md5)
            if p in cache:
                cache[p]['codec'] = codec
        if codec != 'hevc':
            continue
        hevc += 1
        dst = os.path.join(playback_dir, md5 + '.mp4')
        try:
            if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
                skipped += 1
                continue
        except OSError:
            pass
        hevc_tasks.append((src, dst))

    if cache_path:
        try:
            tmp = cache_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(cache, fh, ensure_ascii=False)
            os.replace(tmp, cache_path)
        except OSError:
            pass

    ok = fail = 0
    if hevc_tasks:
        if progress:
            progress(0, f'视频转码 0/{len(hevc_tasks)}')
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_transcode_one, s, d, ffmpeg) for s, d in hevc_tasks]
            for i, f in enumerate(futs, 1):
                if f.result():
                    ok += 1
                else:
                    fail += 1
                if progress:
                    progress(int(i / len(hevc_tasks) * 100),
                             f'视频转码 {i}/{len(hevc_tasks)}')
    return {'selected': selected, 'hevc': hevc, 'transcoded': ok,
            'skipped': skipped, 'failed': fail}


def _plan_voices(media_db, voices_dir):
    c = sqlite3.connect(media_db)
    names = {rid: u for rid, u in c.execute('select rowid, user_name from Name2Id')}
    rows = c.execute(
        'select chat_name_id, create_time, local_id, voice_data from VoiceInfo '
        'where voice_data is not null').fetchall()
    c.close()
    pending, skipped = [], 0
    for cid, ctime, lid, blob in rows:
        chat = re.sub(r'[\\/:*?"<>|]', '_', names.get(cid, f'id_{cid}'))[:80]
        dt = datetime.fromtimestamp(ctime).strftime('%Y%m%d_%H%M%S')
        out = os.path.join(voices_dir, chat, f'{dt}_{lid}.wav')
        if os.path.exists(out):
            skipped += 1
            continue
        pending.append((out, blob))
    return pending, skipped


# ---------------------------------------------------------------- 总编排
class _Progress:
    def __init__(self, cb, weights):
        self.cb = cb
        self.weights = {k: v for k, v in weights.items() if v > 0}
        total_w = sum(self.weights.values()) or 1
        self.weights = {k: v / total_w for k, v in self.weights.items()}
        self.frac = {k: 0.0 for k in self.weights}
        self.msg = {k: '' for k in self.weights}
        self.lock = threading.Lock()

    def report(self, stage, frac, message=''):
        with self.lock:
            self.frac[stage] = max(0.0, min(1.0, frac))
            if message:
                self.msg[stage] = message
            pct = sum(self.frac[k] * self.weights[k] for k in self.weights) * 100
            lines = [v for v in self.msg.values() if v]
        self.cb(int(pct), ' / '.join(lines))


def prepare_media(attach_dir, images_dir, voices_dir, media_db, wxid, codes,
                  workers=None, do_images=True, do_hevc=True,
                  do_voices=True, do_videos=True, video_roots=None,
                  video_cache='', progress=None):
    """并发执行媒体处理，返回统计"""
    workers = workers or default_workers()
    progress = progress or (lambda p, m='': None)

    stages = {}
    if do_images:
        stages['images'] = 55
        stages['hevc'] = 30 if do_hevc else 0
    if do_voices:
        stages['voices'] = 15 if do_images else 100
    if do_videos and video_roots:
        stages['videos'] = 10
    prog = _Progress(progress, stages or {'noop': 1})
    result = {}

    def run_images():
        attach = attach_dir
        derived = derive_image_key(attach, wxid, codes)
        if not derived:
            raise RuntimeError('无法推导图片密钥（kvcomm code 未找到或版本不匹配）')
        _, aes_key, xor_key = derived
        pending, skipped = _plan_images(attach, images_dir)
        prog.report('images', 0, f'图片待解密 {len(pending)}，已跳过 {skipped}')
        tasks = [(c, aes_key, xor_key) for c in _chunks(pending, CHUNK_FILES)]
        ok = fail = 0
        formats = {}
        if tasks:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(_image_batch_worker, t) for t in tasks]
                for i, f in enumerate(as_completed(futs), 1):
                    o, fa, fm = f.result()
                    ok += o
                    fail += fa
                    for k, v in fm.items():
                        formats[k] = formats.get(k, 0) + v
                    prog.report('images', i / len(tasks),
                                f'图片 {ok + fail}/{len(pending)}')
        prog.report('images', 1, f'图片完成 {ok}，跳过 {skipped}，失败 {fail}')
        result['images'] = {'total': len(pending) + skipped, 'ok': ok,
                            'skipped': skipped, 'failed': fail, 'formats': formats}

        if do_hevc:
            pending_h, skipped_h = _plan_wxam(images_dir)
            prog.report('hevc', 0, f'WxAM 待转换 {len(pending_h)}，已跳过 {skipped_h}')
            tasks_h = list(_chunks(pending_h, max(50, CHUNK_FILES // 4)))
            okh = failh = 0
            if tasks_h:
                with ProcessPoolExecutor(max_workers=workers) as ex:
                    futs = [ex.submit(_wxam_batch_worker, t) for t in tasks_h]
                    for i, f in enumerate(as_completed(futs), 1):
                        o, fa = f.result()
                        okh += o
                        failh += fa
                        prog.report('hevc', i / len(tasks_h),
                                    f'WxAM {okh + failh}/{len(pending_h)}')
            prog.report('hevc', 1, f'WxAM 完成 {okh}，跳过 {skipped_h}，失败 {failh}')
            result['hevc'] = {'total': len(pending_h) + skipped_h, 'ok': okh,
                              'skipped': skipped_h, 'failed': failh}

    def run_voices():
        if not os.path.exists(media_db):
            result['voices'] = {'error': '未找到 media_0.db'}
            prog.report('voices', 1, '未找到语音数据库')
            return
        pending, skipped = _plan_voices(media_db, voices_dir)
        prog.report('voices', 0, f'语音待转换 {len(pending)}，已跳过 {skipped}')
        tasks = list(_chunks(pending, 100))
        ok = fail = 0
        if tasks:
            with ProcessPoolExecutor(max_workers=max(2, workers // 2)) as ex:
                futs = [ex.submit(_voice_batch_worker, t) for t in tasks]
                for i, f in enumerate(as_completed(futs), 1):
                    o, fa = f.result()
                    ok += o
                    fail += fa
                    prog.report('voices', i / len(tasks), f'语音 {ok + fail}/{len(pending)}')
        prog.report('voices', 1, f'语音完成 {ok}，跳过 {skipped}，失败 {fail}')
        result['voices'] = {'total': len(pending) + skipped, 'ok': ok,
                            'skipped': skipped, 'failed': fail}

    def run_videos():
        if not video_roots:
            prog.report('videos', 1, '未发现视频目录')
            return
        prog.report('videos', 0, '正在建立视频索引...')
        idx = build_video_index(
            video_roots, video_cache,
            progress=lambda p: prog.report('videos', p / 100,
                                           f'视频索引 {p}%'))
        result['videos'] = {'total': len(idx)}
        prog.report('videos', 1,
                    f'视频索引完成，共 {len(idx)} 个（导出时按需转码）')

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = []
        if do_images:
            futures.append(ex.submit(run_images))
        if do_voices:
            futures.append(ex.submit(run_voices))
        if do_videos and video_roots:
            futures.append(ex.submit(run_videos))
        for f in futures:
            f.result()

    prog.report(next(iter(prog.weights)), 1, '媒体处理完成')
    return result
