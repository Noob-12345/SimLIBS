"""单任务非阻塞控制器；Windows Job Object 保证所属浏览器树被回收。"""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
from .models import Parameters, BatchSpec, ScanSpec
from .settings import UI_ROOT
from .storage import write_json, read_manifest


class OwnedProcessTree:
    def __init__(self, process):
        self.process = process
        self.handle = None
        if sys.platform != 'win32':
            return
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                        ('flags', wintypes.DWORD), ('min_set', ctypes.c_size_t), ('max_set', ctypes.c_size_t),
                        ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                        ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class Counters(ctypes.Structure):
            _fields_ = [(key, ctypes.c_ulonglong) for key in ('read', 'write', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', Counters), ('process_mem', ctypes.c_size_t),
                        ('job_mem', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel = kernel
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.AssignProcessToJobObject(handle, wintypes.HANDLE(int(process._handle))):
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            kernel.CloseHandle(handle)
            raise
        self.handle = handle

    def close(self):
        if self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        elif sys.platform != 'win32' and self.process.poll() is None:
            import os
            import signal
            os.killpg(self.process.pid, signal.SIGTERM)


class JobController:
    def __init__(self, settings, worker_module='simlibs_ui.worker'):
        self.settings = settings
        self.worker_module = worker_module
        self.process = None
        self.tree = None
        self.directory = None
        self.job_id = None
        self.state = 'IDLE'
        self.last_result = None
        self.result_path = None
        self.error = ''
        self._offset = 0
        self._pending = None
        self._cancel_at = None
        self._deadline = None
        self._log = None

    @property
    def busy(self):
        return self.state in ('RUNNING', 'CANCELLING')

    def start(self, kind, **payload):
        if self.busy:
            raise ValueError('已有任务正在运行，请先等待或取消')
        s = self.settings.validated()
        if kind in ('single', 'batch', 'scan', 'advanced'):
            p = Parameters.from_dict(payload['parameters'])
            payload['parameters'] = p.to_dict()
            if kind=='advanced':
                from .advanced import effective
                effective(p,payload['advanced'])
            if kind == 'batch':
                from .storage import validate_compositions
                import pandas as pd
                BatchSpec(**payload['spec']).validated(p,check_cells=payload.get('template_plan') is None)
                validate_compositions(pd.DataFrame(payload['compositions']))
            elif kind == 'scan':
                ScanSpec(**payload['spec']).validated(p)
        self.job_id = uuid.uuid4().hex
        self.directory = Path(s.output).resolve() / '.jobs' / self.job_id
        self.directory.mkdir(parents=True)
        request = dict(payload, kind=kind, job_id=self.job_id, settings=s.to_dict(), directory=str(self.directory))
        path = self.directory / 'request.json'
        write_json(path, request)
        self._offset, self._pending, self._cancel_at = 0, None, None
        self.error = ''
        self._deadline = time.monotonic() + max(30, s.dynamic_deadline if kind in ('batch', 'scan', 'single') else 600)
        self._log = (self.directory / 'worker.log').open('w', encoding='utf-8')
        try:
            self.process = subprocess.Popen([s.python, '-B', '-m', self.worker_module, str(path)], cwd=str(UI_ROOT),
                                            stdin=subprocess.DEVNULL, stdout=self._log, stderr=self._log,
                                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                                            start_new_session=sys.platform != 'win32')
            self.tree = OwnedProcessTree(self.process)
            self.state = 'RUNNING'
            (self.directory / 'go').touch()
        except Exception:
            if self.process and self.process.poll() is None:
                self.process.terminate()  # 启动门未开启，尚无子浏览器。
            self._close_handles()
            self.state = 'FAILED'
            raise
        return self.job_id

    def cancel(self):
        if self.busy and self.state != 'CANCELLING':
            (self.directory / 'cancel').touch()
            self._cancel_at = time.monotonic()
            self.state = 'CANCELLING'

    def _close_handles(self):
        if self.tree:
            self.tree.close()
            self.tree = None
        if self._log:
            self._log.close()
            self._log = None

    def force_close(self):
        if self.busy:
            self.cancel()
        self._close_handles()

    def poll(self):
        if not self.busy:
            return []
        messages = []
        events = self.directory / 'events.jsonl'
        if events.exists():
            with events.open('rb') as stream:
                stream.seek(self._offset)
                while True:
                    start = stream.tell()
                    line = stream.readline()
                    if not line or not line.endswith(b'\n'):
                        self._offset = start
                        break
                    self._offset = stream.tell()
                    message = json.loads(line.decode('utf-8'))
                    if message.get('job_id') != self.job_id:
                        continue
                    messages.append(message)
                    if message['event'] == 'progress' and 'deadline' in message:
                        self._deadline = time.monotonic() + float(message['deadline'])
                    if message['event'] in ('success', 'error', 'cancelled'):
                        self._pending = message
        now = time.monotonic()
        if self.state == 'CANCELLING' and now - self._cancel_at >= .8:
            self._close_handles()
        elif self.state == 'RUNNING' and now > self._deadline:
            self.error = '任务超时，已清理本任务进程树；请缩小范围或检查网络/驱动后重试'
            self._pending = {'event': 'error', 'message': self.error}
            self._close_handles()
        if self.process.poll() is not None:
            self._close_handles()  # 即使父进程异常退出，也关闭同属 Job 的 Chrome。
            if self.state == 'CANCELLING':
                self.state = 'CANCELLED'
            elif self._pending and self._pending['event'] == 'success':
                try:
                    result = read_manifest(self._pending['path'])
                    self.last_result = result
                    self.result_path = self._pending['path']
                    self.state = 'SUCCEEDED'
                except Exception as exc:
                    self.error = f'结果文件读取失败：{exc}'
                    self.state = 'FAILED'
            elif self._pending and self._pending['event'] == 'cancelled':
                self.state = 'CANCELLED'
            else:
                self.state = 'FAILED'
                self.error = (self._pending or {}).get('message') or f'worker 异常退出（{self.process.returncode}），详见 {self.directory / "worker.log"}'
            messages.append({'job_id': self.job_id, 'event': 'finished', 'state': self.state, 'message': self.error})
        return messages
