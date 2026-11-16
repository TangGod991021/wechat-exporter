# -*- coding: utf-8 -*-
"""后台任务管理：长任务异步执行 + 进度查询 + 互斥/取消"""
import threading
import time
import traceback
import uuid


class JobBusy(RuntimeError):
    """同一类型的任务已在运行"""


class JobCancelled(RuntimeError):
    """任务被用户取消"""


class Job:
    def __init__(self, kind):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.status = 'running'      # running | done | error | cancelled
        self.progress = 0
        self.message = ''
        self.logs = []
        self.result = None
        self.error = ''
        self.cancelled = False
        self.started = time.time()
        self.finished = None

    def update(self, progress=None, message=None):
        # 每次进度更新都是一次取消检查点；长任务的回调会被频繁调用
        if self.cancelled:
            raise JobCancelled('任务已取消')
        if progress is not None:
            self.progress = max(0, min(100, int(progress)))
        if message:
            self.message = message
            self.logs.append(message)
            self.logs = self.logs[-80:]

    def to_dict(self):
        return {
            'id': self.id, 'kind': self.kind, 'status': self.status,
            'progress': self.progress, 'message': self.message,
            'logs': self.logs, 'result': self.result, 'error': self.error,
            'elapsed': round((self.finished or time.time()) - self.started, 1),
        }


class JobManager:
    def __init__(self, log_file=None):
        self._jobs = {}
        self._active = {}   # kind -> job id
        self._lock = threading.Lock()
        self.log_file = str(log_file) if log_file else ''

    def _write_log(self, text):
        if not self.log_file:
            return
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {text}\n')
        except OSError:
            pass

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def start(self, kind, fn):
        """fn(job) 在后台线程执行；同类任务互斥"""
        job = Job(kind)
        with self._lock:
            if kind in self._active:
                raise JobBusy(f'已有 {kind} 任务正在运行，请等待完成')
            self._jobs[job.id] = job
            self._active[kind] = job.id

        def runner():
            try:
                job.result = fn(job)
                job.status = 'done'
                job.progress = 100
            except JobCancelled:
                job.status = 'cancelled'
                job.message = '任务已取消'
                job.logs.append('任务已取消')
            except Exception as e:  # noqa: BLE001
                job.status = 'error'
                job.error = f'{type(e).__name__}: {e}'
                job.logs.append(traceback.format_exc()[-1500:])
                self._write_log(f"[{kind}] {job.id} FAILED {job.error}\n"
                                f'{traceback.format_exc()[-4000:]}')
            finally:
                job.finished = time.time()
                with self._lock:
                    if self._active.get(kind) == job.id:
                        del self._active[kind]

        threading.Thread(target=runner, daemon=True).start()
        return job.id

    def cancel(self, job_id):
        """请求取消；任务在下一个进度回调处退出"""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != 'running':
                return False
            job.cancelled = True
            return True
