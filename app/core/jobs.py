# -*- coding: utf-8 -*-
"""后台任务管理：长任务异步执行 + 进度查询"""
import threading
import time
import traceback
import uuid


class Job:
    def __init__(self, kind):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.status = 'running'      # running | done | error
        self.progress = 0
        self.message = ''
        self.logs = []
        self.result = None
        self.error = ''
        self.started = time.time()
        self.finished = None

    def update(self, progress=None, message=None):
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
    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def start(self, kind, fn):
        """fn(job) 在后台线程执行"""
        job = Job(kind)
        with self._lock:
            self._jobs[job.id] = job

        def runner():
            try:
                job.result = fn(job)
                job.status = 'done'
                job.progress = 100
            except Exception as e:  # noqa: BLE001
                job.status = 'error'
                job.error = f'{type(e).__name__}: {e}'
                job.logs.append(traceback.format_exc()[-1500:])
            finally:
                job.finished = time.time()

        threading.Thread(target=runner, daemon=True).start()
        return job.id
