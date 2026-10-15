"""simLIBS Web UI —— MOCK 后端。

按 backend_api.SimlibsBackend 协议实现的模拟引擎：
- 合成光谱为简化洛伦兹峰模型（示意数据，非真实 NIST 结果）；
- 任务在后台线程顺序执行，通过 EventQueue 推送事件，支持协作式取消；
- 导出为纯标准库实现（PNG/GIF 仅在环境已有 Pillow 时可用）。

真实程序接入时，用包装 simlibs_ui 包的实现替换本模块（server.py 一行切换）。
"""
from __future__ import annotations

import io
import json
import math
import platform
import random
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend_api import (
    MAX_PREVIEW_POINTS, TERMINAL_STATUSES, ApiError, EventQueue, ExportPayload,
    JobEvent, CommonParams, SingleRequest, BatchRequest, ScanRequest, scan_values,
)

# ----------------------------------------------------------------------
# 合成光谱模型（与设计稿一致：洛伦兹峰 + 噪声，纯示意）
# ----------------------------------------------------------------------
PEAKS: List[Tuple[float, float, str, str]] = [
    (434.05, .42, "N", "H"), (486.13, .72, "N", "H"), (656.28, 1.0, "N", "H"), (410.17, .30, "N", "H"),
    (388.90, .30, "N", "He"), (587.56, .55, "N", "He"), (706.52, .24, "N", "He"),
    (373.71, .62, "N", "Fe"), (404.58, .38, "N", "Fe"), (438.35, .30, "N", "Fe"),
    (526.95, .22, "N", "Fe"), (561.56, .16, "N", "Fe"),
    (390.30, .45, "N", "Mo"), (550.65, .26, "N", "Mo"), (603.07, .18, "N", "Mo"), (379.83, .24, "N", "Mo"),
    (400.87, .40, "N", "W"), (429.46, .34, "N", "W"), (498.26, .20, "N", "W"), (430.21, .18, "N", "W"),
    (516.73, .30, "I", "Fe II"), (527.04, .22, "I", "Fe II"), (492.39, .16, "I", "Fe II"),
    (261.36, .30, "I", "Mo II"), (291.14, .22, "I", "Mo II"),
    (281.62, .26, "I", "W II"), (263.48, .20, "I", "W II"),
    (447.15, .35, "I", "He II"), (468.57, .28, "I", "He II"),
    (410.00, .24, "I", "H II"), (486.30, .20, "I", "H II"),
]


def _base(el: str) -> str:
    return el.split(" ")[0]


def calc_spectrum(te: float, ne: float, resolution: int, low: float, up: float,
                  elements: List[str], n: int = 900, raw: bool = True,
                  seed: int = 0) -> Dict[str, List[float]]:
    els = {_base(e) for e in elements}
    iw = 1.0 / (1.0 + math.exp(-(te - 1.35) * 3))
    nw = 0.15 + 0.85 / (1.0 + math.exp((te - 1.6) * 3))
    broad = min(3.2, 1.0 + (ne / 1e17) * 0.9)
    rnd = random.Random(seed)
    xs: List[float] = []
    ys: List[float] = []
    yi: List[float] = []
    for i in range(n):
        x = low + (up - low) * i / (n - 1)
        v = 0.028
        vi = 0.0
        for wl, st, typ, el in PEAKS:
            if _base(el) not in els:
                continue
            w = iw if typ == "I" else nw
            if w < 0.02:
                continue
            hw = max(0.018, (wl / resolution) * broad)
            g = hw / 2.0
            d = x - wl
            lorentz = g * g / (d * d + g * g)
            v += st * w * lorentz
            if typ == "I":
                vi += st * w * lorentz
        if raw:
            v += (rnd.random() - 0.5) * 2 * 0.045 * (0.25 + v)
        xs.append(round(x, 4))
        ys.append(round(max(0.0, v), 6))
        yi.append(round(max(0.0, vi), 6))
    return {"xs": xs, "ys": ys, "yi": yi}


# ----------------------------------------------------------------------
# MOCK 引擎
# ----------------------------------------------------------------------
class MockBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self._cancel_flags: Dict[str, threading.Event] = {}
        self._settings: Dict[str, Any] = {
            "connect_timeout": 10, "read_timeout": 30, "page_load": 45,
            "static_deadline": 60, "dynamic_deadline": 180,
            "tls_verify": True, "python": r"D:\Anaconda3\envs\simLIBS\python.exe",
            "chrome": "(自动检测)", "driver": "留空则自动获取匹配版本",
            "output_dir": r"…\UI\output",
        }
        self._seed_history()

    # ---- 历史任务（示意） ----
    def _seed_history(self) -> None:
        now = time.time()
        seeds = [
            ("j-7f3a21", "单次模拟", "H 100% · 650–660nm · R1000", "completed", "3.2 s", None),
            ("j-7f3a1e", "批量 dataset", "48 样本 · seed=42", "completed", "2 分 41 秒", None),
            ("j-7f39d8", "扫描动画", "Te 0.6→1.8 · 41 帧", "completed", "1 分 55 秒", None),
            ("j-7f39b0", "批量 dataset", "96 样本 · static", "failed", "38.4 s", "NIST 读取超时（MOCK 历史）"),
            ("j-7f39ac", "单次模拟", "W/Fe/Mo · 200–1000nm", "cancelled", "12.1 s", None),
        ]
        for i, (jid, kind, summary, status, duration, error) in enumerate(seeds):
            with self._lock:
                self._jobs[jid] = {
                    "job_id": jid, "kind": kind, "status": status, "summary": summary,
                    "progress": 100.0 if status == "completed" else 0.0,
                    "duration": duration, "error": error,
                    "created": datetime.fromtimestamp(now - 3600 * (i + 1)).strftime("%m-%d %H:%M"),
                    "mock_history": True, "events": [],
                }

    # ---- 协议：状态与默认值 ----
    def api_version(self) -> str:
        return "1"

    def engine_status(self) -> Dict[str, Any]:
        with self._lock:
            running = sum(1 for j in self._jobs.values() if j["status"] in ("queued", "running"))
        return {
            "engine": "mock",
            "engine_label": "MOCK（未接真实程序）",
            "api_version": self.api_version(),
            "python": platform.python_version(),
            "nist": "mock · 未联线",
            "nist_ok": True,
            "chrome": "mock",
            "driver": "mock",
            "jobs_running": running,
        }

    def default_params(self) -> Dict[str, Any]:
        return {
            "params": {
                "te": 1.0, "ne": 1e17, "resolution": 5000, "low_w": 350, "up_w": 560,
                "max_ion_charge": 2, "mode": "dynamic", "headless": True, "resample": False,
                "intensity_scale":"photon",
            },
            "composition": [{"el": "W", "pct": 50}, {"el": "Fe", "pct": 25}, {"el": "Mo", "pct": 25}],
            "title": "W Fe Mo composition · Te=1.00 eV",
        }

    def preview(self, params: CommonParams, elements: List[str]) -> Dict[str, Any]:
        params.check_points()
        n = min(900, MAX_PREVIEW_POINTS)
        spec = calc_spectrum(params.te, params.ne, params.resolution, params.low_w, params.up_w,
                             elements, n=n, raw=True,
                             seed=int(params.te * 100) * 7919 + int(params.ne) + params.resolution)
        return spec

    # ---- 协议：任务 ----
    def start_single(self, req: SingleRequest) -> str:
        els = [it.el for it in req.composition if it.pct > 0]
        comp_txt = " / ".join(f"{it.el} {it.pct:g}%" for it in req.composition)
        stages = [
            (0.25, "info", f"[worker] 任务 {{jid}} 启动 · python {platform.python_version()} · headless={req.params.headless}"),
            (0.95, "", f"[adapter] SimulatedLIBS(Te={req.params.te:g}, Ne={req.params.ne:.3g}, "
                       f"R={req.params.resolution}, {req.params.low_w:g}–{req.params.up_w:g} nm, {req.params.mode})"),
            (1.70, "info", "[nist] GET physics.nist.gov/cgi-bin/ASD/ie.pl … 200 OK (1.24 s) [MOCK]"),
            (2.40, "", f"[parse] 列映射 Wavelength (nm) × {' / '.join(e + ' I' for e in els)} → 213 行"),
            (3.00, "", f"[interp] CubicSpline · {'主动重采样 ' + str(req.params.resample_step) + ' nm' if req.params.resample else 'NIST 网格'}"),
            (3.50, "ok", "[done] manifest.json → output/.jobs/{jid} · SHA256 已记录 [MOCK]"),
        ]
        return self._launch("单次模拟", req.params.summary() + " · " + comp_txt, req.params,
                            [it.el for it in req.composition], stages)

    def start_batch(self, req: BatchRequest) -> str:
        summary = f"{req.n_samples} 样本 · seed={req.seed} · {req.params.summary()}"
        return self._launch("批量模拟", summary, req.params, [], None, batch_req=req)

    def start_scan(self, req: ScanRequest) -> str:
        comp_txt = " / ".join(f"{it.el} {it.pct:g}%" for it in req.composition)
        summary = f"{req.axis.upper()} {req.start:g}→{req.end:g} · {req.frames} 帧 · {req.params.summary()} · {comp_txt}"
        return self._launch("扫描动画", summary, req.params, [it.el for it in req.composition],
                            None, scan_req=req)

    def _launch(self, kind: str, summary: str, params: CommonParams, elements: List[str],
                stages: Optional[List[Tuple[float, str, str]]], batch_req: Optional[BatchRequest] = None,
                scan_req: Optional[ScanRequest] = None) -> str:
        jid = "j-" + uuid.uuid4().hex[:6]
        job = {
            "job_id": jid, "kind": kind, "status": "queued", "summary": summary,
            "progress": 0.0, "duration": "-", "error": None,
            "created": datetime.now().strftime("%m-%d %H:%M"), "events": [],
        }
        with self._lock:
            self._jobs[jid] = job
            self._cancel_flags[jid] = threading.Event()
        threading.Thread(target=self._run, daemon=True,
                         args=(jid, params, elements, stages, batch_req, scan_req)).start()
        return jid

    # ---- 事件工具 ----
    def _emit(self, jid: str, ev_type: str, message: str = "", level: str = "info",
              status: Optional[str] = None, progress: Optional[float] = None,
              final: bool = False) -> None:
        with self._lock:
            job = self._jobs[jid]
            ev = JobEvent(seq=len(job["events"]), ts=datetime.now().strftime("%H:%M:%S.%f")[:-5],
                          job_id=jid, type=ev_type, message=message, level=level,
                          status=status, progress=progress, final=final)
            job["events"].append(ev)
            subs = job.get("subs", [])
            for q in list(subs):
                q.push(ev)
            if status:
                job["status"] = status
            if progress is not None:
                job["progress"] = progress
        self._console(ev)

    def _console(self, ev: JobEvent) -> None:
        try:
            print(f"[{ev.ts}] {ev.job_id} {ev.type} {ev.status or ''} {ev.message}", flush=True)
        except Exception:
            pass

    def _cancelled(self, jid: str) -> bool:
        return self._cancel_flags[jid].is_set()

    def _sleep(self, jid: str, seconds: float) -> bool:
        """可中断睡眠；返回 False 表示已取消。"""
        return not self._cancel_flags[jid].wait(seconds)

    # ---- 任务执行 ----
    def _run(self, jid: str, params: CommonParams, elements: List[str],
             stages: Optional[List[Tuple[float, str, str]]], batch_req: Optional[BatchRequest],
             scan_req: Optional[ScanRequest]) -> None:
        t0 = time.time()
        self._emit(jid, "status", status="running", progress=0)
        try:
            if stages:
                total = stages[-1][0]
                prev = 0.0
                for delay, level, msg in stages:
                    if not self._sleep(jid, max(0.0, delay - prev)):
                        raise _Cancelled()
                    prev = delay
                    self._emit(jid, "log", message=msg.replace("{jid}", jid), level=level or "info",
                               progress=round(delay / total * 100, 1))
                    self._emit(jid, "progress", progress=round(delay / total * 100, 1))
                result = self._single_result(jid, params, elements)
            elif batch_req is not None:
                result = self._batch_run(jid, batch_req)
            elif scan_req is not None:
                result = self._scan_run(jid, scan_req, elements)
            else:  # pragma: no cover
                raise ApiError(500, "未知任务类型")
            with self._lock:
                self._results[jid] = result
                self._jobs[jid]["duration"] = f"{time.time() - t0:.1f} s"
            self._emit(jid, "log", message=f"[done] 结果就绪 · {self._jobs[jid]['duration']}", level="ok")
            self._emit(jid, "status", status="completed", progress=100.0, final=True)
        except _Cancelled:
            with self._lock:
                self._jobs[jid]["duration"] = f"{time.time() - t0:.1f} s"
            # 语义：失败或取消不伪造成功；保留上一成功结果
            self._emit(jid, "log", message="[ui] 已取消 · 保留上一次成功图谱", level="warn")
            self._emit(jid, "status", status="cancelled", final=True)
        except ApiError as exc:
            with self._lock:
                self._jobs[jid]["duration"] = f"{time.time() - t0:.1f} s"
                self._jobs[jid]["error"] = exc.message
            self._emit(jid, "log", message=f"[error] {exc.message}", level="error")
            self._emit(jid, "status", status="failed", final=True)
        except Exception as exc:  # 任何未预期异常都不能让任务线程静默死亡
            import traceback
            traceback.print_exc()
            msg = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._jobs[jid]["duration"] = f"{time.time() - t0:.1f} s"
                self._jobs[jid]["error"] = msg
            self._emit(jid, "log", message=f"[error] 内部错误 · {msg}", level="error")
            self._emit(jid, "status", status="failed", final=True)
        finally:
            with self._lock:
                job = self._jobs[jid]
                for q in list(job.get("subs", [])):
                    q.close()
                job["subs"] = []

    def _single_result(self, jid: str, params: CommonParams, elements: List[str]) -> Dict[str, Any]:
        spec = calc_spectrum(params.te, params.ne, params.resolution, params.low_w, params.up_w,
                             elements, n=900, raw=True, seed=int(params.te * 100) * 7919 + params.resolution)
        active = [e for e in elements if e]
        return {
            "kind": "single",
            "xs": spec["xs"], "ys": spec["ys"], "yi": [],
            "meta": {
                "source": "MOCK · 本地合成谱（非 NIST）",
                "intensity_scale":"unknown","requested_intensity_scale":params.intensity_scale,
                "intensity_units":"a.u. (MOCK synthesis; no physical flux conversion)",
                "http": "200 [MOCK]",
                "rows": f"{len(active)} 元素 · 213 行",
                "points": f"{len(spec['xs']):,} 点",
                "duration": self._jobs[jid]["duration"],
                "sha256": uuid.uuid4().hex[:4] + "…",
                "ne_actual": f"{params.ne:.3g}",
                "elements": active,
            },
        }

    def _batch_run(self, jid: str, req: BatchRequest) -> Dict[str, Any]:
        rng = random.Random(req.seed)
        self._emit(jid, "log", message=f"[batch] 生成 {req.n_samples} 样本（seed={req.seed}）· 顺序执行")
        samples: List[Dict[str, Any]] = []
        done = 0
        interval = 0.03
        for i in range(req.n_samples):
            if not self._sleep(jid, interval):
                raise _Cancelled()
            te = req.te_range[0] + (req.te_range[1] - req.te_range[0]) * rng.random()
            ne = 10 ** (req.ne_range[0] + (req.ne_range[1] - req.ne_range[0]) * rng.random())
            comp = rng.choice(req.compositions)
            name = f"{comp.name}-{i + 1:03d}"
            samples.append({
                "name": name, "te": round(te, 3), "ne": float(f"{ne:.3g}"),
                "composition": [{"el": it.el, "pct": it.pct} for it in comp.items],
            })
            done += 1
            progress = round((i + 1) / req.n_samples * 100, 1)
            self._emit(jid, "progress", progress=progress)
            if (i + 1) % max(1, req.n_samples // 12) == 0 or i == req.n_samples - 1:
                self._emit(jid, "log", message=f"[batch] {done}/{req.n_samples} 完成 · 当前 {name} "
                                               f"(Te={te:.2f}, Ne={ne:.3g})", progress=progress)
        wide_cols = ["λ [nm]", *[it.el for it in req.compositions[0].items], "name", "Te[eV]", "Ne[cm^-3]"]
        wide_rows = [
            [350.00, 0.021, 0.142, "—", samples[0]["name"], samples[0]["te"], samples[0]["ne"]],
            [350.01, 0.022, 0.148, "—", samples[0]["name"], samples[0]["te"], samples[0]["ne"]],
            [350.02, 0.020, 0.151, "—", samples[0]["name"], samples[0]["te"], samples[0]["ne"]],
        ]
        return {
            "kind": "batch",
            "intensity_scale":"unknown","requested_intensity_scale":req.params.intensity_scale,
            "summary": {"total": req.n_samples, "completed": done, "failed": 0, "seed": req.seed},
            "samples": samples[:12],
            "training_package": {"available": False, "batch_size": req.batch_size,
                                 "reason": "MOCK 为示意数据；训练包需切换真实引擎并完成批量模拟"},
            "wide": {"cols": wide_cols, "rows": wide_rows, "note": "宽表仅示意 · 真实后端输出全量宽表"},
        }

    def _scan_run(self, jid: str, req: ScanRequest, elements: List[str]) -> Dict[str, Any]:
        values = scan_values(req.start, req.end, req.frames)
        unit = {"te": "eV", "ne": "×10^x cm⁻³", "r": ""}[req.axis]
        self._emit(jid, "log", message=f"[scan] 共 {req.frames} 帧（= {req.frames} 次 NIST 请求 [MOCK]）· "
                                       f"轴 {req.axis.upper()} · {req.start:g}→{req.end:g} {unit}")
        frames: List[Dict[str, Any]] = []
        els = elements or ["W", "Fe", "Mo"]
        for i, v in enumerate(values):
            if not self._sleep(jid, 0.04):
                raise _Cancelled()
            te, ne, res = req.params.te, req.params.ne, req.params.resolution
            if req.axis == "te":
                te = v
            elif req.axis == "ne":
                ne = 10 ** v
            else:
                res = int(round(v))
            spec = calc_spectrum(te, ne, res, req.params.low_w, req.params.up_w, els,
                                 n=320, raw=True, seed=i * 131 + req.params.resolution)
            frames.append({"value": round(v, 4), **spec})
            progress = round((i + 1) / req.frames * 100, 1)
            self._emit(jid, "progress", progress=progress)
            if (i + 1) % max(1, req.frames // 8) == 0 or i == req.frames - 1:
                self._emit(jid, "log", message=f"[scan] 帧 {i + 1}/{req.frames} · "
                                               f"{req.axis.upper()}={v:.3g} {unit}", progress=progress)
        return {
            "kind": "scan",
            "intensity_scale":"unknown","requested_intensity_scale":req.params.intensity_scale,
            "axis": req.axis, "unit": unit, "frames": frames,
            "params_summary": req.params.summary(),
        }

    # ---- 协议：查询 / 取消 ----
    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] in TERMINAL_STATUSES:
                return False
            self._cancel_flags[job_id].set()
        return True

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            jobs = [self._job_view(j) for j in self._jobs.values()]
        jobs.sort(key=lambda x: x["created"], reverse=True)
        return jobs

    def _job_view(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return {k: job.get(k) for k in
                ("job_id", "kind", "status", "summary", "progress", "duration", "error",
                 "created", "mock_history")}

    def get_job(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ApiError(404, f"任务不存在：{job_id}", "not_found")
            view = self._job_view(job)
            view["events"] = [ev.to_dict() for ev in job["events"]]
        return view

    def get_result(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            result = self._results.get(job_id)
        if not job:
            raise ApiError(404, f"任务不存在：{job_id}", "not_found")
        if job["status"] != "completed" or result is None:
            raise ApiError(409, f"任务尚未成功完成（当前 {job['status']}）", "no_result")
        return result

    def subscribe(self, job_id: str) -> EventQueue:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ApiError(404, f"任务不存在：{job_id}", "not_found")
            q = EventQueue()
            job.setdefault("subs", []).append(q)
        return q

    # ---- 协议：导出 ----
    def export(self, job_id: str, kind: str, frame: Optional[int] = None) -> ExportPayload:
        job = self.get_job(job_id)
        if job["status"] != "completed":
            raise ApiError(409, "只有成功完成的任务才能导出", "no_result")
        result = self.get_result(job_id)
        if kind == "csv":
            xs, ys = result["xs"], result["ys"]
            lines = [f"# simLIBS Web UI MOCK 导出 · 任务 {job_id}",
                     f"# {result['meta']['source']} · {job['summary']}",
                     "wavelength,intensity"]
            lines += [f"{x},{y}" for x, y in zip(xs, ys)]
            return ExportPayload("\n".join(lines), "text/csv; charset=utf-8", f"{job_id}_spectrum.csv")
        if kind == "json":
            manifest = {
                "job": job, "api_version": self.api_version(), "engine": self.engine_status(),
                "meta": result.get("meta"), "note": "MOCK 导出 · 真实后端将包含源哈希/NIST URL/参数证据",
            }
            return ExportPayload(json.dumps(manifest, ensure_ascii=False, indent=2),
                                 "application/json; charset=utf-8", f"{job_id}_manifest.json")
        if kind == "png":
            return self._export_png(result, f"{job_id}_spectrum.png", frame)
        if kind == "gif":
            return self._export_gif(result, f"{job_id}_scan.gif")
        raise ApiError(400, f"未知导出类型：{kind}", "validation")

    def _require_pil(self):
        try:
            from PIL import Image  # noqa: deep import，仅在需要时
            return Image
        except Exception:
            raise ApiError(501, "当前 Python 环境缺少 Pillow，无法生成 PNG/GIF（真实后端将使用 UI 环境的 Pillow）",
                           "unavailable")

    def _export_png(self, result: Dict[str, Any], filename: str,
                    frame: Optional[int] = None) -> ExportPayload:
        Image = self._require_pil()
        xs, ys = result["xs"], result["ys"]
        if result.get("kind") == "scan":
            frames = result.get("frames") or []
            if frame is None or not (0 <= frame < len(frames)):
                raise ApiError(400, f"扫描任务导出 PNG 需要有效帧号（0–{len(frames) - 1}）", "validation")
            xs, ys = frames[frame]["xs"], frames[frame]["ys"]
        w, h = 900, 300
        img = Image.new("RGB", (w, h), (12, 16, 22))
        px = img.load()
        ymax = max(ys) or 1.0
        for i in range(len(xs)):
            x = int(i / (len(xs) - 1) * (w - 60)) + 45
            y = int((h - 40) - ys[i] / (ymax * 1.12) * (h - 70))
            for dy in range(max(0, y), min(h - 1, y + 3)):
                if 0 <= x < w:
                    px[x, dy] = (34, 211, 238)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return ExportPayload(buf.getvalue(), "image/png", filename)

    def _export_gif(self, result: Dict[str, Any], filename: str) -> ExportPayload:
        Image = self._require_pil()
        frames = result.get("frames") or []
        if not frames:
            raise ApiError(400, "该任务不是扫描动画任务", "validation")
        imgs = []
        w, h = 640, 240
        for f in frames:
            img = Image.new("RGB", (w, h), (12, 16, 22))
            px = img.load()
            ys = f["ys"]
            ymax = max(ys) or 1.0
            for i in range(len(ys)):
                x = int(i / (len(ys) - 1) * (w - 50)) + 35
                y = int((h - 30) - ys[i] / (ymax * 1.12) * (h - 60))
                for dy in range(max(0, y), min(h - 1, y + 2)):
                    px[x, dy] = (34, 211, 238)
            imgs.append(img)
        buf = io.BytesIO()
        imgs[0].save(buf, "GIF", save_all=True, append_images=imgs[1:], duration=140, loop=0)
        return ExportPayload(buf.getvalue(), "image/gif", filename)

    # ---- 协议：设置 ----
    def get_settings(self) -> Dict[str, Any]:
        return dict(self._settings)

    def save_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in settings.items():
            if k in self._settings:
                self._settings[k] = v
        return self.get_settings()


def roman(i: int) -> str:
    return ["I", "II", "III"][i] if i < 3 else "I"


class _Cancelled(Exception):
    pass
