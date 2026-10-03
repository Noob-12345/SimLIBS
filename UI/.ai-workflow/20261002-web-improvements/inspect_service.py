"""只读核对精确8517 PID、PEB当前目录/命令、项目主页及无活动任务。"""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import struct
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
pid=int(sys.argv[1])
assert c.sizeof(c.c_void_p)==8
k=c.WinDLL('kernel32',use_last_error=True);n=c.WinDLL('ntdll')
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
k.ReadProcessMemory.argtypes=[w.HANDLE,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
k.CloseHandle.argtypes=[w.HANDLE]
class Basic(c.Structure):
    _fields_=[('reserved',c.c_void_p),('peb',c.c_void_p),('more',c.c_void_p*2),('pid',c.c_void_p),('parent',c.c_void_p)]
n.NtQueryInformationProcess.argtypes=[w.HANDLE,c.c_uint,c.c_void_p,c.c_ulong,c.POINTER(c.c_ulong)]
handle=k.OpenProcess(0x410,False,pid)
if not handle:raise c.WinError(c.get_last_error())
def read(address,size):
    buffer=c.create_string_buffer(size);got=c.c_size_t()
    if not k.ReadProcessMemory(handle,address,buffer,size,c.byref(got)):raise c.WinError(c.get_last_error())
    assert got.value==size
    return buffer.raw
def unicode(address):
    length,_,pointer=struct.unpack('<HH4xQ',read(address,16))
    return read(pointer,length).decode('utf-16-le')
try:
    basic=Basic();returned=c.c_ulong()
    assert n.NtQueryInformationProcess(handle,0,c.byref(basic),c.sizeof(basic),c.byref(returned))==0
    params=struct.unpack('<Q',read(basic.peb+0x20,8))[0]
    directory=unicode(params+0x38);image=unicode(params+0x60);command=unicode(params+0x70)
finally:k.CloseHandle(handle)
assert Path(directory).samefile(ROOT/'web'),directory
assert Path(image).samefile(r'D:\Anaconda3\envs\simLIBS\python.exe'),image
assert 'server.py' in command and '--port' in command and '8517' in command and '--no-browser' in command,command
with urllib.request.urlopen('http://127.0.0.1:8517/',timeout=5) as r:page=r.read()
local=(ROOT/'web'/'static'/'index.html').read_bytes()
assert page==local,'served page does not match this project'
with urllib.request.urlopen('http://127.0.0.1:8517/api/jobs',timeout=5) as r:jobs=json.load(r)['jobs']
active=[j for j in jobs if j.get('status') not in ('completed','failed','cancelled')]
assert not active,active
result=dict(pid=pid,current_directory=directory,image_path=image,command_line=command,
            home_sha256=hashlib.sha256(page).hexdigest(),jobs=jobs,active_jobs=active)
(Path(__file__).parent/(sys.argv[2] if len(sys.argv)>2 else 'service-owner-before.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True,indent=2))
