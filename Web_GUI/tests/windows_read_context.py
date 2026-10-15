"""新进程使用仅经 Authenticated Users 授权的受限令牌读取训练文件；不修改 ACL。"""
import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import sys
import threading


@contextlib.contextmanager
def authenticated_reader():
    advapi=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    class SidAndAttributes(ctypes.Structure):
        _fields_=[('Sid',ctypes.c_void_p),('Attributes',wintypes.DWORD)]
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.LocalFree.argtypes=[ctypes.c_void_p]
    advapi.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]
    advapi.ConvertStringSidToSidW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_void_p)]
    advapi.CreateRestrictedToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
        wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(SidAndAttributes),ctypes.POINTER(wintypes.HANDLE)]
    advapi.ImpersonateLoggedOnUser.argtypes=[wintypes.HANDLE]
    original, restricted, sid=wintypes.HANDLE(),wintypes.HANDLE(),ctypes.c_void_p()
    def check(ok):
        if not ok:raise ctypes.WinError(ctypes.get_last_error())
    try:
        check(advapi.OpenProcessToken(kernel.GetCurrentProcess(),0x000E,ctypes.byref(original)))
        check(advapi.ConvertStringSidToSidW('S-1-5-11',ctypes.byref(sid)))
        restrictions=SidAndAttributes(sid,0)
        check(advapi.CreateRestrictedToken(original,1,0,None,0,None,1,ctypes.byref(restrictions),ctypes.byref(restricted)))
        check(advapi.ImpersonateLoggedOnUser(restricted))
        try:yield
        finally:check(advapi.RevertToSelf())
    finally:
        if restricted:kernel.CloseHandle(restricted)
        if original:kernel.CloseHandle(original)
        if sid:kernel.LocalFree(sid)


def main():
    # 先导入库，再收紧读权限，避免依赖安装目录影响目标文件的权限验证。
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root));sys.path.insert(0,str(root/'web'))
    from real_backend import RealBackend
    from simlibs_ui.storage import read_manifest
    config=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    report={'context':'new process; DISABLE_MAX_PRIVILEGE; restricting SID Authenticated Users S-1-5-11',
            'files':[],'exports':[]}
    with authenticated_reader():
        for filename in config['files']:
            path=Path(filename)
            try:
                data=path.read_bytes()
                report['files'].append({'path':str(path),'readable':True,'sha256':hashlib.sha256(data).hexdigest()})
            except OSError as exc:
                report['files'].append({'path':str(path),'readable':False,'error':str(exc)})
        backend=RealBackend.__new__(RealBackend);backend._lock=threading.Lock();backend._jobs={}
        for record in config.get('jobs',[]):
            jid=record['job_id']
            try:
                manifest=read_manifest(record['manifest'])
                backend._jobs[jid]={'status':'completed','manifest':manifest,'result_path':record['manifest']}
                exported=backend.export(jid,'training')
                report['exports'].append({'job_id':jid,'succeeded':True,'sha256':hashlib.sha256(exported.payload).hexdigest()})
            except OSError as exc:report['exports'].append({'job_id':jid,'succeeded':False,'error':str(exc)})
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
