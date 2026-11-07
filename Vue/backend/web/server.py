"""simLIBS Web UI 服务器 —— 纯标准库（http.server）：静态前端 + REST + SSE。

启动：
    python server.py [--port 8517] [--no-browser]

接入真实程序：只需实现 backend_api.SimlibsBackend 协议并替换 create_backend()，
不修改任何现有程序文件，前端与路由零改动。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import hmac
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import backend_api
from backend_api import (
    TERMINAL_STATUSES, ApiError, BatchRequest, CommonParams, ScanRequest, SingleRequest,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_PORT = 8517

os.environ.setdefault("MPLBACKEND", "Agg")  # 导出 PNG/GIF 在无界面环境渲染


def create_backend() -> backend_api.SimlibsBackend:
    """后端选择：默认接入真实引擎（包装 simlibs_ui 包）。

    设置环境变量 SIMLIBS_WEB_BACKEND=mock 可切换回 MOCK 演示引擎。
    """
    from real_backend import RealBackend
    return RealBackend()


TOKEN = os.environ.get('SIMLIBS_SESSION_TOKEN', '')
if not TOKEN: raise RuntimeError('必须配置 SIMLIBS_SESSION_TOKEN，禁止无鉴权设置写入')
TRUSTED = {'http://tauri.localhost', 'https://tauri.localhost', 'tauri://localhost',
           'http://localhost:1420', 'http://127.0.0.1:1420'}
BACKEND = create_backend()

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "simlibs-web/1.0"
    protocol_version = "HTTP/1.1"

    def _authorized(self):
        origin = self.headers.get('Origin')
        if origin and origin not in TRUSTED:
            self._json({'error': {'message': '不可信 origin'}}, 403); return False
        if not hmac.compare_digest(self.headers.get('X-SimLIBS-Token', ''), TOKEN):
            self._json({'error': {'message': '无效 session token'}}, 401); return False
        return True

    def end_headers(self):
        origin = self.headers.get('Origin')
        if origin in TRUSTED:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Expose-Headers', 'Content-Disposition')
        super().end_headers()

    def do_OPTIONS(self):
        if self.headers.get('Origin') not in TRUSTED:
            self._json({'error': {'message': '不可信 origin'}}, 403); return
        self._send(204, b'', 'text/plain', {'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                   'Access-Control-Allow-Headers': 'Content-Type, X-SimLIBS-Token'})

    # ---- 基础工具 ----
    def log_message(self, fmt: str, *args: Any) -> None:  # 精简访问日志
        pass

    def handle_one_request(self):
        # 浏览器关闭 keep-alive 连接属正常现象，不打印回溯
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError):
            self.close_connection = True

    def _send(self, status: int, body: bytes, content_type: str,
              extra: Optional[dict] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _json(self, obj: Any, status: int = 200) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _fail(self, exc: Exception) -> None:
        if isinstance(exc, ApiError):
            self._json(exc.to_dict(), exc.status)
            return
        import traceback
        traceback.print_exc()
        self._json({"error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}"}}, 500)

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ApiError(400, f"请求体不是合法 JSON：{exc}", "validation")

    # ---- 路由 ----
    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized(): return
        try:
            url = urlparse(self.path)
            parts = [p for p in url.path.split("/") if p]
            if not parts or parts[0] != "api":
                self._static(url.path)
                return
            q = parse_qs(url.query)
            if parts == ["api", "status"]:
                self._json(BACKEND.engine_status(q.get('mode',['local'])[0]))
            elif parts == ['api', 'diagnostics']:
                from simlibs_ui.runtime_diagnostics import inspect_runtime
                self._json(inspect_runtime(BACKEND.engine_status('local').get('local'), BACKEND.get_settings()))
            elif parts == ["api", "params"]:
                self._json(BACKEND.default_params())
            elif parts == ["api", "settings"]:
                self._json(BACKEND.get_settings())
            elif parts == ["api", "preview"]:
                def qget(key: str, default: str) -> str:
                    return q.get(key, [default])[0]
                pd = {
                    "te": _num(qget("te", "1.0")),
                    "ne": _num(qget("ne", "1e17")),
                    "resolution": _num(qget("resolution", "5000")),
                    "low_w": _num(qget("low_w", "350")),
                    "up_w": _num(qget("up_w", "560")),
                    "max_ion_charge": _num(qget("max_ion_charge", "2")),
                    "mode": qget("mode", "dynamic"),
                    "mode_version":_num(qget('mode_version','1')),
                    "headless": True,
                    "resample": qget("resample", "0") == "1",
                    "intensity_scale":qget('intensity_scale','photon'),
                }
                params = CommonParams.from_api(pd)
                elements = [e for e in (q.get("elements", [""])[0]).split(",") if e.strip()]
                self._json(BACKEND.preview(params, elements))
            elif parts == ["api", "jobs"]:
                self._json({"jobs": BACKEND.list_jobs()})
            elif len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                self._json(BACKEND.get_job(parts[2]))
            elif len(parts) == 4 and parts[1] == "jobs" and parts[3] == "result":
                if 'frame' in q:
                    try:frame=int(q['frame'][0])
                    except ValueError:raise ApiError(400,'frame 必须为整数','validation')
                    self._json(BACKEND.get_result(parts[2],frame=frame))
                else:self._json(BACKEND.get_result(parts[2],sample=int(q['sample'][0]) if 'sample' in q else None))
            elif len(parts) == 4 and parts[1] == "jobs" and parts[3] == "events":
                self._sse(parts[2])
            elif len(parts) == 4 and parts[1] == "jobs" and parts[3] == "export":
                kind = q.get("kind", ["csv"])[0]
                frame: Optional[int] = None
                if "frame" in q:
                    try:
                        frame = int(q["frame"][0])
                    except ValueError:
                        raise ApiError(400, "frame 必须是整数", "validation")
                payload = BACKEND.export(parts[2], kind, frame)
                body = payload.payload
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self._send(200, body, payload.media_type,
                           {"Content-Disposition": f'attachment; filename="{payload.filename}"'})
            else:
                raise ApiError(404, f"未知接口：{url.path}", "not_found")
        except ApiError as exc:
            self._fail(exc)
        except Exception as exc:
            self._fail(exc)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized(): return
        try:
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            body = self._body()
            if parts == ['api', 'shutdown']:
                self._json({'stopping': True})
                def stop():
                    BACKEND.shutdown(); self.server.shutdown()
                threading.Thread(target=stop, daemon=True).start()
            elif parts == ['api', 'simulate', 'advanced']:
                self._json({'job_id': BACKEND.start_advanced(body)})
            elif parts == ["api", "simulate", "single"]:
                self._json({"job_id": BACKEND.start_single(SingleRequest.from_api(body))})
            elif parts==['api','templates','validate']:
                req=BatchRequest.from_api(body)
                if req.template_plan is None:raise ApiError(400,'需要template_csv','validation')
                BACKEND.validate_batch(req)
                self._json({k:v for k,v in req.template_plan.items() if k not in ('source_csv','entries')})
            elif parts == ["api", "simulate", "batch"]:
                self._json({"job_id": BACKEND.start_batch(BatchRequest.from_api(body))})
            elif parts == ["api", "simulate", "scan"]:
                self._json({"job_id": BACKEND.start_scan(ScanRequest.from_api(body))})
            elif len(parts) == 4 and parts[1] == "jobs" and parts[3] == "cancel":
                ok = BACKEND.cancel(parts[2])
                self._json({"cancelled": bool(ok)})
            elif len(parts)==4 and parts[1]=='jobs' and parts[3]=='resume':
                if body:raise ApiError(400,'续跑不得附加新参数/模板','validation')
                self._json({'job_id':BACKEND.resume(parts[2])})
            elif parts == ["api", "settings"]:
                self._json(BACKEND.save_settings(body))
            else:
                raise ApiError(404, f"未知接口：{urlparse(self.path).path}", "not_found")
        except ApiError as exc:
            self._fail(exc)
        except Exception as exc:
            self._fail(exc)

    # ---- 静态文件 ----
    def _static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if not str(target).startswith(str(STATIC_DIR)) or not target.is_file():
            self._send(404, "404 Not Found".encode("utf-8"), "text/plain; charset=utf-8")
            return
        body = target.read_bytes()
        ctype = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, body, ctype)

    # ---- SSE 事件流 ----
    def _sse(self, job_id: str) -> None:
        job = BACKEND.get_job(job_id)  # 不存在时抛 404
        self.close_connection = True   # SSE 结束后由服务端关闭连接，浏览器会自动重连
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        q = BACKEND.subscribe(job_id)
        try:
            for ev in list(job["events"]):     # 先重放已有事件（dict 或 JobEvent 均可）
                data = ev if isinstance(ev, dict) else ev.to_dict()
                if not self._write_sse(data):
                    return
            if job["status"] in TERMINAL_STATUSES:
                return
            while True:
                kind, item = q.get(timeout=12)
                if kind == "timeout":
                    if not self._write_sse(None):
                        return
                    continue
                if kind == "close":
                    return
                data = item.to_dict()
                if not self._write_sse(data):
                    return
                if data.get("final"):
                    return
        except ApiError:
            pass
        finally:
            q.close()

    def _write_sse(self, ev: Optional[dict]) -> bool:
        try:
            if ev is None:
                self.wfile.write(b": ping\n\n")
            else:
                data = json.dumps(ev, ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return False


def _num(value: str) -> Any:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    return int(f) if f == int(f) and "." not in str(value) and "e" not in str(value).lower() else f


def main() -> int:
    parser = argparse.ArgumentParser(description="simLIBS Web UI server")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("SIMLIBS_WEB_PORT", DEFAULT_PORT)))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    ready = os.environ.get('SIMLIBS_READY_FILE')
    if ready:
        Path(ready).write_text(json.dumps({'endpoint': url.rstrip('/'), 'pid': os.getpid()}), encoding='utf-8')
    print(f"simLIBS Web UI · {url}")
    print(f"引擎：{BACKEND.engine_status()['engine_label']}")
    print("Ctrl+C 停止")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        BACKEND.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
