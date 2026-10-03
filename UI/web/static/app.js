/* ================================================================
   simLIBS Studio · 前端应用
   所有数据经 /api/* 接口获取；任务进度经 SSE (/api/jobs/{id}/events) 推送。
   后端不可达时降级为纯前端示意模式（离线横幅提示）。
   ================================================================ */
"use strict";

/* ---------- 小工具 ---------- */
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const SUPMAP = { '0':'⁰','1':'¹','2':'²','3':'³','4':'⁴','5':'⁵','6':'⁶','7':'⁷','8':'⁸','9':'⁹','.':'·','-':'⁻' };
const sup = v => String(v).split('').map(c => SUPMAP[c] || c).join('');
const TERMINAL = ['completed', 'failed', 'cancelled'];
const KIND_PAGE = { '单次模拟': 'single', '批量 dataset': 'batch', '扫描动画': 'scan' };

function toast(type, title, msg) {
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.innerHTML = `<div><b>${title}</b><small>${msg || ''}</small></div>`;
  $('#toasts').appendChild(t);
  setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 260); }, 3600);
}

async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  let resp;
  try { resp = await fetch(url, opt); }
  catch (e) { const err = new Error('后端服务不可达'); err.network = true; throw err; }
  if (!resp.ok) {
    const j = await resp.json().catch(() => null);
    const err = new Error(j && j.error ? j.error.message : ('HTTP ' + resp.status));
    err.status = resp.status; err.network = resp.status >= 500;
    throw err;
  }
  return resp.json();
}

/* ---------- 全局状态 ---------- */
const state = {
  offline: false,
  previewUnsupported: false,   // 真实引擎无合成预览（501）后缓存，避免反复请求
  comp: [{ el: 'W', pct: 50 }, { el: 'Fe', pct: 25 }, { el: 'Mo', pct: 25 }],
  mode: 'dynamic',
  broadening: 'nist',   // nist=服务端/页面展宽；local=本地线表展宽
  views: { raw: true, interp: true, ion: true, norm: false },
  hasResult: false,
  engineMock: false,
  currentJob: null,     // {id, kind}
  jobFinalized: false,
  scanCache: null,      // {axis, unit, frames:[{value,xs,ys}]}
  scan: { axis: 'te', playing: false, frame: 0, timer: null },
  batchJobId: null,
};

/* ================================================================
   光谱绘制（Canvas）
   ================================================================ */
function setupCanvas(cv) {
  const r = cv.getBoundingClientRect();
  if (r.width < 10) return null;
  const d = window.devicePixelRatio || 1;
  cv.width = Math.round(r.width * d); cv.height = Math.round(r.height * d);
  const ctx = cv.getContext('2d');
  ctx.setTransform(d, 0, 0, d, 0, 0);
  return { ctx, w: r.width, h: r.height };
}
function niceTicks(min, max, count) {
  if (!(max > min) || !Number.isFinite(max-min)) return [min];
  const span = max - min, step0 = span / count, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag, step = (norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10) * mag;
  if (!(step > 0)) return [min,max];
  const t = [], first=Math.ceil(min/step);
  for (let i=0;i<30;i++) { const v=(first+i)*step; if(v>max+step*1e-9)break;t.push(v); }
  return t;
}
function numberLabel(v) { return v === 0 ? '0' : (Math.abs(v)<.001 || Math.abs(v)>=1e4 ? v.toExponential(3) : String(Number(v.toPrecision(7)))); }
function intensityLabel(spec,norm){
  if(norm)return 'Normalized intensity';
  const meta=spec&&spec.meta||{};
  if(meta.source&&meta.source.includes('MOCK'))return 'MOCK intensity [a.u.]';
  let scale=meta.intensity_scale||spec&&spec.intensity_scale;
  if(!scale&&meta.nist_url){const n=new URL(meta.nist_url).searchParams.get('int_scale');scale=n==='1'?'energy':n==='2'?'photon':'unknown';}
  return scale==='energy'?'Energy flux [a.u.]':scale==='photon'?'Photon flux [a.u.]':spec&&spec.illustrative?'Illustrative [a.u.]':'Intensity [a.u.; scale unknown]';
}
function lowerIndex(xs,x) { let a=0,b=xs.length;while(a<b){const m=(a+b)>>1;xs[m]<x?a=m+1:b=m;}return a; }
function drawSpectrum(cv, spec, opts) {
  const s = setupCanvas(cv); if (!s) return;
  const { ctx, w, h } = s;
  const pad = { l: 78, r: 16, t: 14, b: 28 };
  const cw = w - pad.l - pad.r, ch = h - pad.t - pad.b;
  const C = {
    text: cssVar('--muted'), faint: cssVar('--faint'), grid: cssVar('--grid'),
    raw: cssVar('--chart-raw'), main: cssVar('--chart-main'), ion: cssVar('--chart-ion'),
  };
  ctx.clearRect(0, 0, w, h);
  if (!spec || !spec.xs || !spec.xs.length) {
    ctx.fillStyle = C.faint; ctx.font = '12px "Segoe UI", sans-serif'; ctx.textAlign = 'center';
    ctx.fillText(opts.emptyText || '暂无数据', w / 2, h / 2);
    cv._plot = null; return;
  }
  const actual=spec.series || {}, main=actual.interpolated || actual.raw || {xs:spec.xs,ys:spec.ys};
  const available=[main,actual.raw,...(actual.ions||[])].filter(s=>s&&s.xs.length);
  let fullMin=Math.min(...available.map(s=>s.xs[0])),fullMax=Math.max(...available.map(s=>s.xs[s.xs.length-1]));
  if(fullMin===fullMax){fullMin-=.05;fullMax+=.05;}
  let xmin=fullMin,xmax=fullMax;
  { // 交互视窗：左键框选放大 / 中键平移 / 右键复原（cv._view 由 attachChartInteractions 维护）
    let view = cv._view || null;
    if (view) {
      if (Math.abs(view.srcMin - fullMin) > 1e-6 || Math.abs(view.srcMax - fullMax) > 1e-6) {
        cv._view = null; view = null;   // 数据范围已变（新结果/新预设），视窗自动失效
      }
    }
    if (view) {
      xmin=view.xmin;xmax=view.xmax;
    }
  }
  const slice=s=>{const lo=lowerIndex(s.xs,xmin),hi=lowerIndex(s.xs,xmax);return {...s,xs:s.xs.slice(lo,hi+(s.xs[hi]===xmax?1:0)),ys:s.ys.slice(lo,hi+(s.xs[hi]===xmax?1:0))};};
  const lines=[];
  if(opts.views.interp!==false)lines.push({...slice(main),style:'main'});
  if(opts.views.raw&&actual.raw)lines.push({...slice(actual.raw),style:'raw'});
  if(opts.views.ion&&opts.showIon)for(const ion of actual.ions||[])lines.push({...slice(ion),style:'ion'});
  let ymax=0;for(const s of lines)for(const y of s.ys)ymax=Math.max(ymax,y);
  const divisor=ymax>0?ymax:1;
  if(opts.norm){for(const s of lines)s.ys=s.ys.map(y=>y/divisor);ymax=1;}else if(!ymax)ymax=1;
  ymax *= 1.12;
  const X = x => pad.l + (x-xmin)/(xmax-xmin)*cw;
  const Y = v => pad.t + ch - Math.min(1, v / ymax) * ch;

  ctx.strokeStyle = C.grid; ctx.lineWidth = 1; ctx.font = '10px Consolas, monospace';
  niceTicks(0, ymax, 4).forEach(v => { const y = Y(v); ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.fillStyle = C.faint; ctx.textAlign = 'right'; ctx.fillText(numberLabel(v), pad.l - 7, y + 3); });
  niceTicks(xmin,xmax,6).forEach(v => {
    const x = X(v);
    ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + ch); ctx.stroke();
    ctx.fillStyle = C.faint; ctx.textAlign = 'center'; ctx.fillText(v.toFixed(0), x, h - 9); });
  ctx.textAlign = 'center'; ctx.fillText('λ / nm', pad.l + cw / 2, h - 0.5);
  ctx.save();ctx.translate(12,pad.t+ch/2);ctx.rotate(-Math.PI/2);ctx.fillText(intensityLabel(spec,opts.norm),0,0);ctx.restore();

  function line(s, color, widthPx, glow) {
    const nPts=opts.reveal!==undefined?Math.min(s.xs.length,Math.max(1,Math.round(s.xs.length*opts.reveal))):s.xs.length;
    ctx.beginPath();
    for (let i = 0; i < nPts; i++) { const x = X(s.xs[i]), y = Y(s.ys[i]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
    ctx.strokeStyle = color; ctx.lineWidth = widthPx; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    if (glow) { ctx.shadowColor = color; ctx.shadowBlur = 3; }
    ctx.stroke(); ctx.shadowBlur = 0;
  }
  ctx.save();ctx.beginPath();ctx.rect(pad.l,pad.t,cw,ch);ctx.clip();
  for(const s of lines){
    if(s.style==='raw'){
      ctx.fillStyle=C.raw;ctx.globalAlpha=.75;
      for(let i=0;i<s.xs.length;i++){ctx.beginPath();ctx.arc(X(s.xs[i]),Y(s.ys[i]),1.2,0,7);ctx.fill();}
      ctx.globalAlpha=1;
    }else if(s.style==='ion'){ctx.save();ctx.setLineDash([5,4]);line(s,C.ion,1.2,false);ctx.restore();}
    else line(s,C.main,1.4,true);
  }
  ctx.restore();
  const basis=lines.find(s=>s.xs.length)||slice(main);
  cv._plot = { pad,cw,ch,xs:basis.xs,ys:basis.ys,ymax,xmin,xmax,fullMin,fullMax,norm:!!opts.norm };
}
function drawEmpty(cv, text) {
  drawSpectrum(cv, null, { views: {}, emptyText: text });
}

/* ---------- 单次模拟页图表 ---------- */
const specCanvas = $('#specChart'), tooltip = $('#tooltip');
let specData = null;
let singleOpts = null;

function drawSingle(spec, instant = false) {
  specData = spec;
  singleOpts = {
    views: state.views, norm: state.views.norm,
    showIon: !!(spec&&spec.series&&spec.series.ions.length),
  };
  present(specCanvas, spec, singleOpts, instant ? 'instant' : 'morph');
}

function currentParams() {
  return {
    te: parseFloat($('#teSlider').value),
    neExp: parseFloat($('#neSlider').value),
    R: parseInt($('#rSlider').value),
    low: parseFloat($('#lowW').value) || 350,
    up: parseFloat($('#upW').value) || 560,
  };
}
function fillSlider(el) {
  const pct = (el.value - el.min) / (el.max - el.min) * 100;
  el.style.setProperty('--fill', pct + '%');
}
function updateParamLabels() {
  const p = currentParams();
  $('#teVal').textContent = p.te.toFixed(2) + ' eV';
  $('#neVal').textContent = '1.0×10' + sup(p.neExp) + ' cm⁻³';
  $('#rVal').textContent = p.R;
  fillSlider($('#teSlider')); fillSlider($('#neSlider')); fillSlider($('#rSlider'));
}

/* ---------- 预览：优先走接口，后端不可达时本地合成 ---------- */
let previewTimer = null, previewSeq = 0;
function schedulePreview() { clearTimeout(previewTimer); previewTimer = setTimeout(fetchPreview, 90); }
async function fetchPreview() {
  const p = currentParams();
  updateParamLabels();
  $('#legend [data-view=ion]').style.display = state.hasResult?specData&&specData.series&&specData.series.ions.length?'':'none':'none';
  // 已有真实结果：保留图谱直到下次运行（与桌面版“保留上一成功图谱”语义一致）
  if (state.hasResult) return;
  if (p.low >= p.up) { drawEmpty(specCanvas, '波长范围无效：需 0 < 下界 < 上界'); specData = null; return; }
  const els = state.comp.filter(c => c.el.trim()).map(c => c.el.trim());
  const seq = ++previewSeq;
  if (!state.offline && !state.previewUnsupported) {
    try {
      const q = new URLSearchParams({
        te: String(p.te), ne: String(Math.pow(10, p.neExp)), resolution: String(p.R),
        low_w: String(p.low), up_w: String(p.up), mode: state.mode,
        resample: $('#resample').checked ? '1' : '0', elements: els.join(','),
        intensity_scale:$('#intensityScale').value,
      });
      const r = await api('GET', '/api/preview?' + q);
      if (seq !== previewSeq) return;
      specData = r;
      drawSingle(r);
      return;
    } catch (e) {
      if (seq !== previewSeq) return;
      if (e.status === 501) { state.previewUnsupported = true; }  // 真实引擎：无合成预览
      else if (e.network) setOffline(true);
    }
  }
  drawSingle(localCalc(p, els));
}

/* 离线兜底：与 MOCK 后端相同的示意模型 */
const PEAKS = [
  [434.05,.42,'N','H'],[486.13,.72,'N','H'],[656.28,1.0,'N','H'],[410.17,.30,'N','H'],
  [388.90,.30,'N','He'],[587.56,.55,'N','He'],[706.52,.24,'N','He'],
  [373.71,.62,'N','Fe'],[404.58,.38,'N','Fe'],[438.35,.30,'N','Fe'],[526.95,.22,'N','Fe'],[561.56,.16,'N','Fe'],
  [390.30,.45,'N','Mo'],[550.65,.26,'N','Mo'],[603.07,.18,'N','Mo'],[379.83,.24,'N','Mo'],
  [400.87,.40,'N','W'],[429.46,.34,'N','W'],[498.26,.20,'N','W'],[430.21,.18,'N','W'],
  [516.73,.30,'I','Fe II'],[527.04,.22,'I','Fe II'],[492.39,.16,'I','Fe II'],
  [261.36,.30,'I','Mo II'],[291.14,.22,'I','Mo II'],
  [281.62,.26,'I','W II'],[263.48,.20,'I','W II'],
  [447.15,.35,'I','He II'],[468.57,.28,'I','He II'],
  [410.00,.24,'I','H II'],[486.30,.20,'I','H II'],
];
function localCalc(p, els) {
  const set = new Set(els.map(e => e.split(' ')[0]));
  const iw = 1 / (1 + Math.exp(-(p.te - 1.35) * 3));
  const nw = .15 + .85 / (1 + Math.exp((p.te - 1.6) * 3));
  const broad = Math.min(3.2, 1 + Math.pow(10, p.neExp - 17) * .9);
  let seed = Math.round(p.te * 100) * 7919 + p.R;
  const rand = () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  const n = 760, xs = [], ys = [], yi = [];
  for (let i = 0; i < n; i++) {
    const x = p.low + (p.up - p.low) * i / (n - 1);
    let v = 0.028, vi = 0;
    for (const pk of PEAKS) {
      if (!set.has(pk[3].split(' ')[0])) continue;
      const w = pk[2] === 'I' ? iw : nw; if (w < .02) continue;
      const hw = Math.max(.018, (pk[0] / p.R) * broad), g = hw / 2, d = x - pk[0];
      v += pk[1] * w * (g * g / (d * d + g * g));
      if (pk[2] === 'I') vi += pk[1] * w * (g * g / (d * d + g * g));
    }
    v += (rand() - .5) * 2 * .045 * (.25 + v);
    xs.push(x); ys.push(Math.max(0, v)); yi.push(Math.max(0, vi));
  }
  return { xs, ys, yi:[], illustrative:true, intensity_scale:'unknown' };
}

/* ---------- 十字光标 ---------- */
function Xof(cv, i) { const P = cv._plot; return P.pad.l + (P.xs[i] - P.xmin) / (P.xmax-P.xmin) * P.cw; }
function Yof(cv, i) { const P = cv._plot; return P.pad.t + P.ch - Math.min(1, P.ys[i] / (P.ymax || 1)) * P.ch; }
specCanvas.addEventListener('mousemove', e => {
  if (!specData || specCanvas._chartDrag) return;   // 框选/平移拖动期间暂停十字光标
  const r = specCanvas.getBoundingClientRect();
  const px = e.clientX - r.left, py = e.clientY - r.top;
  const A = getAnim(specCanvas);
  const cur = A.disp || specData;
  if (!specCanvas._plot) return;
  const P = specCanvas._plot;
  if (px < P.pad.l || px > P.pad.l + P.cw) { tooltip.style.display = 'none'; fetchPreview(); return; }
  clearTimeout(previewTimer);   // 悬停期间暂停预览重绘，避免清掉十字线
  present(specCanvas, cur, singleOpts || { views: state.views }, 'instant');
  const P2 = specCanvas._plot;
  if(!P2.xs.length)return;
  const at=P2.xmin+(px-P2.pad.l)/P2.cw*(P2.xmax-P2.xmin);
  let i=Math.min(P2.xs.length-1,lowerIndex(P2.xs,at));
  if(i>0&&at-P2.xs[i-1]<P2.xs[i]-at)i--;
  const x = Xof(specCanvas, i), y = Yof(specCanvas, i);
  const ctx = specCanvas.getContext('2d');
  ctx.strokeStyle = cssVar('--border2'); ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(x, P2.pad.t); ctx.lineTo(x, P2.pad.t + P2.ch); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = cssVar('--accent'); ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 7); ctx.fill();
  tooltip.style.display = 'block';
  tooltip.style.left = Math.min(px + 14, r.width - 150) + 'px';
  tooltip.style.top = (py - 34) + 'px';
  tooltip.innerHTML = `<b>${numberLabel(P2.xs[i])} nm</b> · I = ${numberLabel(P2.ys[i])}`;
});
specCanvas.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; schedulePreview(); });

/* ================================================================
   动画基建：光谱呈现三模式（描线 reveal / 形变 morph / 即时 instant）
   ================================================================ */
const REDUCED = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const animators = new WeakMap();   // canvas → {token, disp}
function getAnim(cv) {
  if (!animators.has(cv)) animators.set(cv, { token: 0, disp: null });
  return animators.get(cv);
}
const easeOut = k => 1 - Math.pow(1 - k, 3);

/* present：以指定模式把 spec 呈现到画布，并维护"当前显示值"供悬停/中断续接 */
function present(cv, spec, opts, mode = 'instant') {
  const A = getAnim(cv);
  const token = ++A.token;
  if (REDUCED || mode === 'instant' || !spec || !spec.xs) {
    drawSpectrum(cv, spec, opts);
    A.disp = spec;
    return;
  }
  const prev = A.disp;
  if(spec.series){mode='reveal';}
  const sameGrid = prev && prev.xs && spec.xs &&
    prev.xs.length === spec.xs.length &&
    Math.abs(prev.xs[0] - spec.xs[0]) < 1e-6 &&
    Math.abs(prev.xs[prev.xs.length - 1] - spec.xs[spec.xs.length - 1]) < 1e-6;

  if (mode === 'reveal') {
    A.disp = spec;                      // 描线期间悬停可直接读到目标值
    const t0 = performance.now(), dur = 700;
    (function step(now) {
      if (token !== A.token) return;
      const k = Math.min(1, (now - t0) / dur);
      drawSpectrum(cv, spec, { ...opts, reveal: easeOut(k) });
      if (k < 1) requestAnimationFrame(step);
    })(performance.now());

  } else if (mode === 'morph' && sameGrid) {
    const t0 = performance.now(), dur = 150;
    (function step(now) {
      if (token !== A.token) return;
      const k = Math.min(1, (now - t0) / dur);
      const e = easeOut(k);
      const cur = {
        xs: spec.xs,
        ys: prev.ys.map((v, i) => v + (spec.ys[i] - v) * e),
        yi: prev.yi.map((v, i) => v + (spec.yi[i] - v) * e),
      };
      drawSpectrum(cv, cur, opts);
      A.disp = cur;
      if (k < 1) requestAnimationFrame(step); else A.disp = spec;
    })(performance.now());

  } else {
    drawSpectrum(cv, spec, opts);
    A.disp = spec;
  }
}

/* 数字滚动 */
function countUp(el, target, suffix = '', dur = 650) {
  if (!el) return;
  if (REDUCED) { el.textContent = target + suffix; return; }
  const t0 = performance.now();
  (function step(now) {
    const k = Math.min(1, (now - t0) / dur);
    el.textContent = Math.round(target * easeOut(k)) + suffix;
    if (k < 1) requestAnimationFrame(step);
  })(performance.now());
}
/* 卡片光环脉冲 */
function flashCard(el) {
  if (!el || REDUCED) return;
  el.classList.remove('flash');
  void el.offsetWidth;
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 1100);
}

/* ================================================================
   图表交互：左键框选放大 · 中键拖动平移 · 右键复原
   视窗状态存于 cv._view = {xmin, xmax, srcMin, srcMax}；
   drawSpectrum 依据 _view 切片数据并按可见窗口自适应 y 轴。
   ================================================================ */
function chartPxToData(cv, clientX) {
  const r = cv.getBoundingClientRect(), P = cv._plot;
  if (!P) return null;
  const px = Math.max(P.pad.l, Math.min(r.width - P.pad.r, clientX - r.left));
  const frac = (px - P.pad.l) / P.cw;
  return P.xmin + frac * (P.xmax-P.xmin);
}
function chartSetView(cv, d0, d1) {
  const P = cv._plot; if (!P) return;
  const cur = cv._view;
  const srcMin = cur ? cur.srcMin : P.fullMin;
  const srcMax = cur ? cur.srcMax : P.fullMax;
  const lo = cur ? cur.xmin : srcMin, hi = cur ? cur.xmax : srcMax;
  const xmin = Math.max(lo, Math.min(d0, d1));
  const xmax = Math.min(hi, Math.max(d0, d1));
  if (!(xmax > xmin)) return;
  cv._view = { xmin, xmax, srcMin, srcMax };
}
function chartDrawBand(cv, drag) {
  const P = cv._plot; if (!P) return;
  const r = cv.getBoundingClientRect();
  const x0 = Math.max(P.pad.l, Math.min(drag.px0, drag.px1) - r.left);
  const x1 = Math.min(P.pad.l + P.cw, Math.max(drag.px0, drag.px1) - r.left);
  if (x1 - x0 < 1) return;
  const ctx = cv.getContext('2d');
  ctx.save();
  ctx.fillStyle = cssVar('--accent-soft');
  ctx.strokeStyle = cssVar('--accent');
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 3]);
  ctx.fillRect(x0, P.pad.t, x1 - x0, P.ch);
  ctx.strokeRect(x0 + .5, P.pad.t + .5, x1 - x0 - 1, P.ch - 1);
  ctx.restore();
}
function attachChartInteractions(cv, redraw) {
  cv._view = null;
  cv._chartDrag = null;   // 拖动期间十字光标暂停重绘，避免擦掉选区带
  cv.style.cursor = 'crosshair';
  let drag = null;

  // 中键按下会触发浏览器自动滚动，提前拦截
  cv.addEventListener('mousedown', e => { if (e.button === 1) e.preventDefault(); });

  // 中键按下会触发浏览器自动滚动，提前拦截
  cv.addEventListener('mousedown', e => {
    const P = cv._plot; if (!P) return;
    if (e.button === 1) e.preventDefault();
    if (e.button === 0) {
      drag = { mode: 'select', px0: e.clientX, px1: e.clientX };
    } else if (e.button === 1 && cv._view) {
      drag = { mode: 'pan', x0: e.clientX, v0: { ...cv._view } };
      cv.style.cursor = 'grabbing';
    }
    cv._chartDrag = drag;
  });

  window.addEventListener('mousemove', e => {
    if (!drag) return;
    if (drag.mode === 'select') {
      drag.px1 = e.clientX;
      redraw();               // 先重绘基础图，再叠加选区带
      chartDrawBand(cv, drag);
    } else if (drag.mode === 'pan') {
      const P = cv._plot; if (!P) return;
      const span = drag.v0.xmax - drag.v0.xmin;
      let dx = -(e.clientX - drag.x0) / P.cw * span;
      let xmin = drag.v0.xmin + dx, xmax = drag.v0.xmax + dx;
      if (xmin < drag.v0.srcMin) { xmin = drag.v0.srcMin; xmax = xmin + span; }
      if (xmax > drag.v0.srcMax) { xmax = drag.v0.srcMax; xmin = xmax - span; }
      cv._view = { xmin, xmax, srcMin: drag.v0.srcMin, srcMax: drag.v0.srcMax };
      redraw();
    }
  });

  window.addEventListener('mouseup', e => {
    if (!drag) return;
    if (drag.mode === 'select') {
      drag.px1 = e.clientX;
      const dx = Math.abs(drag.px1 - drag.px0);
      if (dx >= 6) {
        const d0 = chartPxToData(cv, Math.min(drag.px0, drag.px1));
        const d1 = chartPxToData(cv, Math.max(drag.px0, drag.px1));
        chartSetView(cv, d0, d1);       // 放大到选区（y 轴按可见数据自适应）
      }
      redraw();
    }
    drag = null;
    cv._chartDrag = null;
    cv.style.cursor = 'crosshair';
  });

  cv.addEventListener('contextmenu', e => {
    e.preventDefault();                  // 右键复原
    if (cv._view) { cv._view = null; redraw(); }
    if (cv.id === 'specChart') tooltip.style.display = 'none';
  });
}

/* ================================================================
   配比编辑器
   ================================================================ */
const ELEMENT_SYMBOLS='H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og'.split(' ');
let elementMap=new Map(ELEMENT_SYMBOLS.map(e=>[e.toLowerCase(),e]));
function canonicalElement(value){return elementMap.get(String(value).trim().toLowerCase())||null;}
function compositionPayload(){
  const seen=new Set();
  if(!state.comp.length)throw new Error('至少需要一个元素');
  return state.comp.map(c=>{
    const el=canonicalElement(c.el);
    if(!el)throw new Error('无效或空元素符号：'+c.el);
    if(seen.has(el))throw new Error('元素重复：'+el);seen.add(el);
    if(typeof c.pct==='string'&&!c.pct.trim())throw new Error('占比不能为空');
    const pct=Number(c.pct);if(!Number.isFinite(pct)||pct<0)throw new Error('占比必须是有限非负数字');
    return {el,pct};
  });
}
let compositionNotice='';
function balanceComposition(editedIndex=-1,commit=true){
  const values=[];
  for(const c of state.comp){
    if(typeof c.pct==='string'&&!c.pct.trim()){compositionNotice='无效草稿：占比不能为空';return updateSum();}
    const n=Number(c.pct);
    if(!Number.isFinite(n)||n<0){compositionNotice='无效草稿：占比须有限且非负';return updateSum();}
    values.push(n);
  }
  if(!values.length){compositionNotice='至少需要一个元素';return updateSum();}
  const last=values.length-1;
  let prefix=values.slice(0,last).reduce((a,b)=>a+b,0),clipped=-1,message='';
  if(!Number.isFinite(prefix)){compositionNotice='前项总和超出有限范围';return updateSum();}
  if(prefix>100+1e-6){
    if(editedIndex<0||editedIndex>=last){compositionNotice='前项超过100%，请修改某个前项';return updateSum();}
    const others=values.slice(0,last).reduce((a,b,i)=>a+(i===editedIndex?0:b),0);
    if(others>100+1e-6){compositionNotice='其他前项已超过100%，请先修正';return updateSum();}
    const limit=Math.max(0,100-others),overflow=values[editedIndex]-limit;
    values[editedIndex]=limit;prefix=100;clipped=editedIndex;
    message=`超额 ${numberLabel(overflow)}%：末项已减至0%，仅把本次前项限制为 ${numberLabel(limit)}%`;
  }
  const remainder=Math.max(0,100-prefix);
  if(!message&&Math.abs(values[last]-remainder)>1e-6){
    const delta=values[last]-remainder;
    message=delta>0?`末项超额 ${numberLabel(delta)}%，自动采用余额 ${numberLabel(remainder)}%`:`末项自动补足为余额 ${numberLabel(remainder)}%`;
  }
  values[last]=remainder;
  state.comp.forEach((c,i)=>{c.pct=values[i];});
  const rows=$$('#compRows .comp-row');
  rows.forEach((row,i)=>{
    if(i!==editedIndex||commit)row.querySelector('.comp-pct').value=values[i];
    row.querySelector('.comp-bar i').style.width=Math.min(100,values[i])+'%';
  });
  compositionNotice=message||'末元素为自动余额';
  if(message&&commit)toast('warn','配比已平衡',message);
  return updateSum();
}
function renderComp() {
  const box = $('#compRows'); box.innerHTML = '';
  state.comp.forEach((c, idx) => {
    const row = document.createElement('div'); row.className = 'comp-row';
    row.innerHTML = `
      <input class="comp-el" value="${c.el}" maxlength="4" spellcheck="false">
      <input class="comp-pct" type="number" min="0" max="100" step="0.1" value="${c.pct}">
      <span style="color:var(--faint);font-size:12px">%</span>
      <div class="comp-bar"><i style="width:${Math.min(100, c.pct)}%"></i></div>
      <button class="comp-del" title="删除">✕</button>`;
    row.querySelector('.comp-el').addEventListener('input', e => { c.el = e.target.value; updateSum(); schedulePreview(); });
    row.querySelector('.comp-el').addEventListener('blur',e=>{
      const valid=canonicalElement(c.el);if(valid){c.el=valid;e.target.value=valid;}
      updateSum();
    });
    row.querySelector('.comp-pct').addEventListener('input', e => {
      c.pct = e.target.value;
      balanceComposition(idx,false);schedulePreview();
    });
    row.querySelector('.comp-pct').addEventListener('blur',e=>{c.pct=e.target.value;balanceComposition(idx,true);});
    row.querySelector('.comp-del').addEventListener('click', () => { state.comp.splice(idx, 1); renderComp(); schedulePreview(); });
    box.appendChild(row);
  });
  balanceComposition(-1,true);
}
function compSum() {
  let sum=0;
  for(const c of state.comp){if(typeof c.pct==='string'&&!c.pct.trim())return NaN;const n=Number(c.pct);if(!Number.isFinite(n)||n<0)return NaN;sum+=n;}
  return sum;
}
function updateSum() {
  const s = compSum();
  let symbolsValid=true;try{compositionPayload();}catch(e){symbolsValid=false;}
  const ok = Math.abs(s - 100) < 1e-6 && symbolsValid;
  $('#sumRow').className = 'sum-row ' + (ok ? 'ok' : 'bad');
  const el = $('#sumVal');
  el.textContent = Number.isFinite(s)?s.toFixed(6).replace(/\.?0+$/,'')+' %'+(ok?' ✓ · '+compositionNotice:symbolsValid?' · 须为100%':' · 元素/占比无效或重复'):'无效草稿 · '+compositionNotice;
  el.style.color = ok ? 'var(--good)' : 'var(--bad)';
  return ok;
}

/* ================================================================
   任务：启动 / SSE / 完成
   ================================================================ */
let es = null;
function closeES() { if (es) { es.close(); es = null; } }

function appendLog(msg, level, ts) {
  const box = $('#logbox');
  const d = document.createElement('div');
  const cls = { ok: 'ok', info: 'info', warn: 'warnc', error: 'error' }[level] || '';
  d.innerHTML = `<span class="t">[${ts || ''}]</span> <span class="${cls}">${msg}</span>`;
  box.appendChild(d);
  while (box.children.length > 300) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}
function setProgress(pct) {
  pct = Math.max(0, Math.min(100, pct || 0));
  $('#runProgress').style.width = pct + '%';
  $('#enginePct').textContent = Math.round(pct) + '%';
  if (state.currentJob?.kind === '批量 dataset') $('#batchProgress').style.width = pct + '%';
}

function attachJob(jobId, kind) {
  closeES();
  state.currentJob = { id: jobId, kind };
  state.jobFinalized = false;
  subscribe(jobId);
}
function subscribe(jobId) {
  es = new EventSource('/api/jobs/' + jobId + '/events');
  es.onmessage = e => { try { handleJobEvent(JSON.parse(e.data)); } catch (err) {} };
  es.onerror = async () => {
    es.close(); es = null;
    if (state.jobFinalized || state.currentJob?.id !== jobId) return;
    setTimeout(async () => {
      if (state.currentJob?.id !== jobId) return;
      try {
        const j = await api('GET', '/api/jobs/' + jobId);
        if (TERMINAL.includes(j.status)) { finalizeFromJob(j); return; }
        if (!es) subscribe(jobId);
      } catch (err) { if (err.network) setOffline(true); }
    }, 1200);
  };
}

async function handleJobEvent(ev) {
  if (ev.type === 'log') appendLog(ev.message, ev.level, ev.ts);
  if (ev.type === 'progress') {
    setProgress(ev.progress);
    if (state.currentJob?.kind === '扫描动画') {
      $('#scanNote').textContent = '扫描中 · ' + Math.round(ev.progress || 0) + '%';
    }
    if (state.currentJob?.kind === '批量 dataset') {
      $('#batchLiveMeta').textContent = '已完成 ' + Math.round(ev.progress || 0) + '% · ' + state.currentJob.id;
    }
  }
  if (ev.type === 'status') {
    if (ev.status === 'running') setRunningUI(true);
    if (TERMINAL.includes(ev.status)) {
      state.jobFinalized = true;
      closeES();
      setRunningUI(false);
      await finalizeJob(ev.status);
    }
  }
}

function setRunningUI(running) {
  const kind = state.currentJob?.kind;
  $('#runBtnText').textContent = running ? '取消模拟' : (state.hasResult ? '重新模拟' : '开始模拟');
  $('#runBtn').classList.toggle('danger', running);
  $('#enginePill').style.display = running ? '' : 'none';
  if (running) { $('#runProgressWrap').hidden = false; $('#runProgress').style.width = '0%'; }
  else setTimeout(() => { $('#runProgressWrap').hidden = true; }, 600);
  if (kind === '批量 dataset') {
    $('#batchLive').hidden = false;
    $('#batchCancel').hidden = !running;
  }
  if (kind === '扫描动画') {
    $('#scanCancel').hidden = !running;
    $('#scanRun').disabled = running;
  }
  if (!running) {
    $('#batchCancel').hidden = true;
    $('#scanCancel').hidden = true;
    $('#scanRun').disabled = false;
  }
}

async function finalizeJob(status) {
  const job = state.currentJob;
  if (!job) return;
  $('#jobHint').textContent = { completed: '完成', failed: '失败', cancelled: '已取消' }[status] +
    ` · ${job.id}`;
  try {
    if (status === 'completed') {
      const result = await api('GET', '/api/jobs/' + job.id + '/result');
      if (result.kind === 'single') renderSingleResult(job.id, result);
      else if (result.kind === 'scan') { renderScanResult(result); $('#scanNote').textContent = '扫描完成 · 点击播放查看帧动画'; }
      else if (result.kind === 'batch') renderBatchResult(job.id, result);
      if(result.kind==='single')_lastSingleId=job.id;
      if(result.kind==='scan')_lastScanId=job.id;
      toast('ok', '任务完成', job.id + ' · 结果已就绪');
    } else if (status === 'failed') {
      const j = await api('GET', '/api/jobs/' + job.id);
      toast('err', '任务失败', (j.error || '未知错误') + ' · 已保留上一次成功结果');
    } else {
      toast('warn', '任务取消', job.id + ' · 已保留上一次成功结果');
    }
  } catch (e) {
    if (e.status === 409) { /* 结果尚不可用 */ }
    else toast('warn', '获取结果失败', e.message);
  }
  state.currentJob = null;
  loadJobs();
}

async function finalizeFromJob(j) {
  state.jobFinalized = true;
  closeES();
  setRunningUI(false);
  const fake = { status: j.status };
  await finalizeJob(j.status);
}

/* ---------- 单次模拟：运行 ---------- */
function broadeningPayload() {
  const local = state.broadening === 'local';
  const centerRaw = $('#bCenter').value.trim();
  return {
    broadening: state.broadening,
    broaden_convention: $('#bConvention').value,
    broaden_grid_step: parseFloat($('#bGridStep').value) || 0.005,
    broaden_center_decimals: local && centerRaw !== '' ? parseInt(centerRaw) : null,
    broaden_min_rel_int: parseFloat($('#bMinRel').value) || 0,
  };
}
function commonParamsPayload() {
  const p = currentParams();
  return {
    te: p.te, ne: Math.pow(10, p.neExp), resolution: p.R, low_w: p.low, up_w: p.up,
    max_ion_charge: parseInt($('#maxIon').value) || 0,
    mode: state.mode, headless: $('#headless').checked, resample: $('#resample').checked,
    intensity_scale:$('#intensityScale').value,
    ...broadeningPayload(),
  };
}
async function runSingle() {
  if (state.currentJob) { // 运行中 → 取消
    try { await api('POST', '/api/jobs/' + state.currentJob.id + '/cancel'); }
    catch (e) { toast('warn', '取消失败', e.message); }
    return;
  }
  let composition;try{composition=compositionPayload();}catch(e){toast('err','无法启动',e.message);return;}
  if (!updateSum()) { toast('err', '无法启动', '元素占比总和必须为 100%（当前 ' + compSum().toFixed(1) + '%）'); return; }
  if (state.offline) { toast('err', '后端不可用', '请通过 start_web.cmd 或 server.py 启动后再运行模拟'); return; }
  $('#logbox').innerHTML = '';
  appendLog('[ui] 提交单次模拟任务…', 'info');
  try {
    const r = await api('POST', '/api/simulate/single', {
      params: commonParamsPayload(),
      composition,
      title: $('#chartTitle').value,
    });
    $('#previewTag').style.display = 'none';
    attachJob(r.job_id, '单次模拟');
    setRunningUI(true);
  } catch (e) {
    toast('err', e.status === 400 ? '参数校验未通过' : '提交失败', e.message);
  }
}

function renderSingleResult(jobId, result) {
  state.hasResult = true;
  $('#previewTag').style.display = 'none';
  specData = { ...result };
  singleOpts = {
    views: state.views, norm: state.views.norm,
    showIon: !!(result.series&&result.series.ions.length),
  };
  present(specCanvas, specData, singleOpts, 'reveal');   // 结果描线动画
  const m = result.meta || {};
  $('#legend [data-view=ion]').style.display=result.series&&result.series.ions.length?'':'none';
  $('#legend [data-view=raw]').style.display=result.series&&result.series.raw?'':'none';
  const chips = [];
  if (m.source) chips.push(`<span class="chip"><i style="background:${m.source.includes('MOCK') ? 'var(--warn)' : 'var(--good)'}"></i>${m.source}</span>`);
  if (m.http) chips.push(`<span class="chip">NIST ASD · HTTP ${m.http}</span>`);
  if (m.rows) chips.push(`<span class="chip">${m.rows}</span>`);
  if (m.points) chips.push(`<span class="chip">${m.points}</span>`);
  if (m.duration) chips.push(`<span class="chip mono">${m.duration}</span>`);
  if (m.sha256) chips.push(`<span class="chip mono" title="源库文件哈希">SHA256 ${m.sha256}</span>`);
  if (m.ne_actual) chips.push(`<span class="chip">实际 Ne = ${m.ne_actual}</span>`);
  chips.push(`<span class="chip">${intensityLabel(result,false)}</span>`);
  if(m.ions&&m.ions.length)chips.push(`<span class="chip" title="${m.ions.join(' / ')}">离子：${m.ions.join(' / ')}</span>`);
  // 数据路径证据（重塑方案）
  if (m.computation_location) {
    const loc = m.computation_location === 'server' ? '计算：NIST 服务器' : '计算：客户端';
    chips.push(`<span class="chip" title="线强计算位置">${loc}</span>`);
  }
  if (m.broadening) {
    const b = m.broadening === 'local' ? '展宽：本地（线表）' : '展宽：NIST';
    chips.push(`<span class="chip" title="${m.broadening === 'local' && m.line_table_rows ? '线表 ' + m.line_table_rows + ' 行' : '服务端/页面展宽'}">${b}</span>`);
  }
  if (m.actual_resolution != null) {
    const warned = !!m.resolution_warning;
    chips.push(`<span class="chip" ${warned ? 'style="color:var(--warn);border-color:var(--warn)"' : ''} title="${m.resolution_warning || '响应中的实际分辨本领'}">实际 R ${m.actual_resolution}</span>`);
  }
  $('#metaChips').innerHTML = chips.join('');
  $$('#metaChips .chip').forEach((c, i) => { c.style.animationDelay = (i * 70) + 'ms'; });  // 徽章逐个浮现
  flashCard($('#metaChips').closest('.card'));
  $('#runBtnText').textContent = '重新模拟';
}

/* ---------- 导出下载 ---------- */
async function downloadExport(jobId, kind, extra) {
  if (!jobId) { toast('warn', '暂无可导出的结果', '请先成功运行一次模拟'); return; }
  try {
    const resp = await fetch(`/api/jobs/${jobId}/export?kind=${kind}${extra || ''}`);
    if (!resp.ok) {
      const j = await resp.json().catch(() => null);
      toast('warn', '导出不可用', (j && j.error && j.error.message) || ('HTTP ' + resp.status));
      return;
    }
    const blob = await resp.blob();
    const cd = resp.headers.get('Content-Disposition') || '';
    const m = /filename="?([^";]+)"?/.exec(cd);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = m ? m[1] : (jobId + '.' + kind);
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast('ok', '导出完成', a.download);
  } catch (e) { toast('err', '导出失败', String(e.message || e)); }
}

/* ================================================================
   批量 dataset
   ================================================================ */
async function runBatch() {
  if (state.currentJob) { toast('warn', '已有任务在运行', '请等待完成或先取消'); return; }
  if (!updateSum()) { toast('err', '无法启动', '当前配比总和必须为 100%'); return; }
  const teA = +$('#batchTeA').value, teB = +$('#batchTeB').value;
  const neA = +$('#batchNeA').value, neB = +$('#batchNeB').value;
  if (!(teA < teB) || !(neA < neB)) { toast('err', '无法启动', 'Te / Ne 范围需要 min < max'); return; }
  const pp = commonParamsPayload();
  if ($('#batchResample').checked) pp.resample = true;
  try {
    const r = await api('POST', '/api/simulate/batch', {
      params: pp,
      n_samples: parseInt($('#batchCount').value) || 1,
      seed: parseInt($('#batchSeed').value) || 0,
      te_range: [teA, teB], ne_range: [neA, neB],
      compositions: [{ name: 'current', items: compositionPayload() }],
    });
    state.batchJobId = r.job_id;
    $('#batchJobId').textContent = r.job_id;
    $('#batchLive').hidden = false;
    $('#batchProgress').style.width = '0%';
    $('#batchLiveMeta').textContent = '排队中…';
    attachJob(r.job_id, '批量 dataset');
    setRunningUI(true);
    $('#batchLive').hidden = false;
    $('#batchCancel').hidden = false;
  } catch (e) { toast('err', e.status === 400 ? '参数校验未通过' : '提交失败', e.message); }
}

function renderBatchResult(jobId, result) {
  const s = result.summary || {};
  countUp($('#batchTotal'), s.total ?? 0);
  countUp($('#batchDone'), s.completed ?? 0);
  $('#batchFail').textContent = (s.failed || 0) + ' / ' + (s.cancelled || 0);
  $('#batchEta').textContent = '—';
  $('#batchDoneHint').textContent = '任务 ' + jobId + ' 已完成';
  $('#batchLiveMeta').textContent = `完成 ${s.completed}/${s.total} · ${jobId}`;
  flashCard($('#batchLive'));
  const tb = $('#batchBody'); tb.innerHTML = '';
  const fmtNe = v => (typeof v === 'number' && v >= 1e5) ? v.toExponential(2) : v;
  (result.samples || []).forEach((sm, i) => {
    const tr = document.createElement('tr');
    const compHtml = (sm.composition || []).map(c => `<span>${c.el} ${c.pct}%</span>`).join('');
    tr.innerHTML = `<td class="mono">#${String(i + 1).padStart(2, '0')}</td>
      <td><div class="ecomp">${compHtml}</div></td>
      <td class="mono">${sm.te}</td><td class="mono">${fmtNe(sm.ne)}</td>
      <td><span class="tag g">已完成</span></td>`;
    tb.appendChild(tr);
  });
  $('#batchTableNote').textContent = result.samples && result.samples.length
    ? `已完成 ${s.completed} 样本 · 此处显示前 ${result.samples.length} 行（完整数据见宽表导出）`
    : '任务完成后此处显示最近样本。';
  const w = result.wide || {};
  $('#wideHead').innerHTML = (w.cols || []).map(c => `<th>${c}</th>`).join('');
  $('#wideBody').innerHTML = (w.rows || []).map(r => '<tr>' + r.map(v => `<td class="mono">${v}</td>`).join('') + '</tr>').join('');
  $('#wideNote').textContent = (w.note || '任务完成后更新') + ` · ${jobId}`;
}

/* ================================================================
   扫描动画
   ================================================================ */
function scanAxisInfo() {
  const axis = state.scan.axis;
  const from = parseFloat($('#scanFrom').value) || 0, to = parseFloat($('#scanTo').value) || 1;
  const f = parseInt($('#scanFrames').value) || 2;
  return { axis, from, to, f };
}
function renderScanVals() {
  const { axis, from, to, f } = scanAxisInfo();
  const box = $('#scanVals'); box.innerHTML = '';
  if (!(from < to)) return;
  const shown = Math.min(f, 14);
  for (let i = 0; i < shown; i++) {
    const v = from + (to - from) * i / (f - 1);
    const s = document.createElement('span');
    s.textContent = axis === 'r' ? Math.round(v) : v.toFixed(2);
    box.appendChild(s);
  }
  if (f > shown) {
    const e = document.createElement('span');
    e.textContent = `… 共 ${f} 帧（= ${f} 次 NIST 请求）`;
    box.appendChild(e);
  }
}
function drawScanFrame(mode = 'morph') {
  const cv = $('#scanChart');
  const cache = state.scanCache;
  if (!cache || !cache.frames.length) {
    present(cv, null, { views: {}, emptyText: '扫描完成后可在此播放帧动画' }, 'instant');
    $('#frameInfo').textContent = '等待扫描任务';
    return;
  }
  const i = Math.min(state.scan.frame, cache.frames.length - 1);
  const fr = cache.frames[i];
  present(cv, {...fr,intensity_scale:fr.intensity_scale||cache.intensity_scale}, { views: { raw: true, interp: true, ion: false } }, mode);
  const axName = { te: 'Te', ne: 'Ne', r: 'R' }[cache.axis];
  const axUnit = { te: ' eV', ne: '×10^x cm⁻³', r: '' }[cache.axis];
  const valStr = cache.axis === 'ne' ? '10' + sup(fr.value) : (cache.axis === 'r' ? Math.round(fr.value) : fr.value.toFixed(3));
  $('#frameInfo').textContent = `${axName} = ${valStr}${axUnit} · ${i + 1} / ${cache.frames.length}`;
  $('#scanTip').textContent = `帧 ${i + 1} / ${cache.frames.length} · ${axName} = ${valStr}${axUnit}`;
  $$('#scanVals span').forEach((el, k) => el.classList.toggle('cur', k === i));
}
function scanSetFrame(i) {
  const cache = state.scanCache;
  if (!cache) return;
  state.scan.frame = Math.max(0, Math.min(cache.frames.length - 1, i));
  $('#scanSlider').value = state.scan.frame;
  drawScanFrame();
}
function scanPlayToggle() {
  if (!state.scanCache) { toast('warn', '尚无扫描结果', '请先运行一次扫描'); return; }
  state.scan.playing = !state.scan.playing;
  $('#iconPlay').style.display = state.scan.playing ? 'none' : '';
  $('#iconPause').style.display = state.scan.playing ? '' : 'none';
  if (state.scan.playing) {
    state.scan.timer = setInterval(() => {
      const n = state.scanCache.frames.length;
      scanSetFrame((state.scan.frame + 1) % n);
    }, 140);
  } else clearInterval(state.scan.timer);
}

async function runScan() {
  if (state.currentJob) { toast('warn', '已有任务在运行', '请等待完成或先取消'); return; }
  const { axis, from, to, f } = scanAxisInfo();
  if (!(from < to)) { toast('err', '无法启动', '扫描需要 起始值 < 结束值'); return; }
  try {
    const r = await api('POST', '/api/simulate/scan', {
      params: commonParamsPayload(), axis, start: from, end: to, frames: f,
      composition: compositionPayload(),
    });
    $('#scanNote').textContent = '扫描中 · 0%';
    attachJob(r.job_id, '扫描动画');
    setRunningUI(true);
    $('#scanCancel').hidden = false;
    $('#scanRun').disabled = true;
  } catch (e) { toast('err', e.status === 400 ? '参数校验未通过' : '提交失败', e.message); }
}

function renderScanResult(result) {
  state.scanCache = result;
  state.scan.frame = 0;
  $('#scanSlider').max = result.frames.length - 1;
  $('#scanSlider').value = 0;
  $('#scanSlider').disabled = false;
  $('#gifBtn').disabled = false;
  $('#framePngBtn').disabled = false;
  drawScanFrame('reveal');   // 首帧描线呈现
  // 播放初始化
  if (!state.scan.playing) { $('#iconPlay').style.display = ''; $('#iconPause').style.display = 'none'; }
}

/* ================================================================
   任务记录页
   ================================================================ */
const STATUS_TAG = { completed: ['g', '成功'], failed: ['r', '失败'], cancelled: ['y', '已取消'], running: ['b', '运行中'], queued: ['n', '排队中'] };
async function loadJobs() {
  if (state.offline) return;
  try {
    const r = await api('GET', '/api/jobs');
    const tb = $('#jobsBody'); tb.innerHTML = '';
    r.jobs.forEach(j => {
      const [cls, label] = STATUS_TAG[j.status] || ['n', j.status];
      const tr = document.createElement('tr');
      tr.innerHTML = `<td class="mono">${j.job_id}${j.mock_history ? ' <span class="tag n">历史示意</span>' : ''}</td>
        <td>${j.kind}</td><td class="mono" style="max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${j.summary || ''}</td>
        <td><span class="tag ${cls}">${label}</span></td>
        <td class="mono">${j.status === 'running' ? (j.progress || 0).toFixed(0) + '%' : '—'}</td>
        <td class="mono">${j.duration || '—'}</td>`;
      tb.appendChild(tr);
    });
  } catch (e) { if (e.network) setOffline(true); }
}

/* ================================================================
   设置页
   ================================================================ */
const SET_FIELDS = ['connect_timeout', 'read_timeout', 'page_load', 'static_deadline', 'tls_verify',
  'python', 'chrome', 'driver', 'output_dir'];
let settingsLoaded = false;
async function loadSettings(force) {
  if (state.offline || (settingsLoaded && !force)) return;
  try {
    const s = await api('GET', '/api/settings');
    SET_FIELDS.forEach(k => {
      const el = $('#st_' + k); if (!el) return;
      if (el.type === 'checkbox') el.checked = !!s[k]; else el.value = s[k] ?? '';
    });
    settingsLoaded = true;
  } catch (e) {}
}
async function saveSettings() {
  const payload = {};
  SET_FIELDS.forEach(k => {
    const el = $('#st_' + k); if (!el) return;
    payload[k] = el.type === 'checkbox' ? el.checked : (el.type === 'number' ? +el.value : el.value);
  });
  try {
    await api('POST', '/api/settings', payload);
    toast('ok', '配置已保存', 'MOCK 设置保存在内存中 · 真实后端将持久化');
  } catch (e) { toast('err', '保存失败', e.message); }
}

/* ================================================================
   引擎状态 / 离线模式
   ================================================================ */
function applyStatus(st) {
  $('#stPy').textContent = st.python || '—';
  $('#stNist').textContent = st.nist || '—';
  $('#stChrome').textContent = st.chrome || '—';
  $('#stEngine').textContent = st.engine_label || st.engine || '—';
  $('#stNistDot').className = 'dot ' + (st.nist_ok ? 'g' : 'off');
  state.engineMock = st.engine === 'mock';
  $('#mockBadge').hidden = !state.engineMock;
  state.previewUnsupported = !state.engineMock;   // 真实引擎：预览端点返回 501
}
function setOffline(off) {
  if (state.offline === off) return;
  state.offline = off;
  $('#offlineBanner').hidden = !off;
  if (off) {
    ['#stNist', '#stPy', '#stChrome', '#stEngine'].forEach(s => $(s).textContent = '—');
    $('#stNistDot').className = 'dot off';
    $('#mockBadge').hidden = true;
    toast('warn', '离线示意模式', '未检测到后端服务，图表使用本地示意数据');
  }
}

/* ================================================================
   页面切换 / 主题 / 绑定
   ================================================================ */
const TITLES = {
  single: ['单次模拟', 'Te · Ne · R · 组成 → NIST 光谱'],
  batch: ['批量 dataset', '多样本组成 → 机器学习宽表'],
  scan: ['扫描动画', '参数轴扫描 · 帧动画 · GIF 导出'],
  jobs: ['任务记录', 'output/.jobs 可追溯产物'],
  settings: ['设置', '超时 · 环境 · 输出目录'],
};
function switchPage(p) {
  $$('.nav-item').forEach(x => x.classList.remove('on', 'active'));
  const nav = $$('.nav-item').find(n => n.dataset.page === p);
  if (nav) nav.classList.add('active');
  $$('.page').forEach(pg => pg.classList.toggle('active', pg.dataset.page === p));
  $('#pageTitle').textContent = TITLES[p][0];
  $('#pageSub').textContent = TITLES[p][1];
  requestAnimationFrame(() => {
    if (p === 'single') fetchPreview();
    if (p === 'scan') { renderScanVals(); drawScanFrame(); }
    if (p === 'jobs') loadJobs();
    if (p === 'settings') loadSettings();
  });
}
$$('.nav-item').forEach(n => n.addEventListener('click', () => switchPage(n.dataset.page)));

$('#themeBtn').addEventListener('click', () => {
  const root = document.documentElement;
  const dark = root.dataset.theme === 'dark';
  root.dataset.theme = dark ? 'light' : 'dark';
  $('#iconMoon').style.display = dark ? 'none' : '';
  $('#iconSun').style.display = dark ? '' : 'none';
  drawSingle(specData, true);
  drawScanFrame('instant');
});

/* 单次模拟页绑定 */
['teSlider', 'neSlider', 'rSlider', 'lowW', 'upW'].forEach(id => $('#'+id).addEventListener('input', schedulePreview));
$('#intensityScale').addEventListener('change',()=>{schedulePreview();if(state.hasResult)toast('ok','下次运行尺度已选择','当前成功结果仍保持原尺度与原数据');});
$$('#legend .chip').forEach(ch => ch.addEventListener('click', () => {
  const v = ch.dataset.view;
  if (v === 'norm') { state.views.norm = !state.views.norm; ch.classList.toggle('off', !state.views.norm); }
  else { state.views[v] = !state.views[v]; ch.classList.toggle('off', !state.views[v]); }
  drawSingle(specData, true);
}));
$$('#modeSeg button').forEach(b => b.addEventListener('click', () => {
  $$('#modeSeg button').forEach(x => x.classList.remove('on')); b.classList.add('on');
  state.mode = b.dataset.v; schedulePreview();
}));
$$('#broadSeg button').forEach(b => b.addEventListener('click', () => {
  $$('#broadSeg button').forEach(x => x.classList.remove('on')); b.classList.add('on');
  state.broadening = b.dataset.v;
  $('#broadenParams').hidden = state.broadening !== 'local';
  schedulePreview();
}));
const PRESETS = {
  wfm: { comp: [{ el: 'W', pct: 50 }, { el: 'Fe', pct: 25 }, { el: 'Mo', pct: 25 }], te: 1.0, neExp: 17, R: 1000, low: 200, up: 1000, title: 'W Fe Mo composition · Te=1.00 eV' },
  h: { comp: [{ el: 'H', pct: 100 }], te: 1.0, neExp: 17, R: 1000, low: 650, up: 660, title: 'H 100% · Balmer α · Te=1.00 eV' },
};
$$('.presets [data-preset]').forEach(b => b.addEventListener('click', () => {
  const p = PRESETS[b.dataset.preset];
  state.comp = p.comp.map(c => ({ ...c }));
  $('#teSlider').value = p.te; $('#neSlider').value = p.neExp; $('#rSlider').value = p.R;
  $('#lowW').value = p.low; $('#upW').value = p.up; $('#chartTitle').value = p.title;
  renderComp(); schedulePreview();
  toast('ok', '预设已应用', b.textContent.replace('预设 ', '') + ' · 参数已填写，未联网');
}));
$('#addEl').addEventListener('click', () => {
  if (state.comp.length >= 8) return toast('warn', '已达上限', '最多 8 个元素行');
  state.comp.push({ el: '', pct: 0 }); renderComp();
});
$('#runBtn').addEventListener('click', runSingle);
$$('[data-x]').forEach(b => b.addEventListener('click', () => {
  const kind = b.dataset.x;
  if (kind === 'dir') { toast('ok', '完整结果目录（示意）', '真实后端将创建并重定位 manifest 的结果目录'); return; }
  const jobId = state.hasResult ? lastCompletedSingleId() : null;
  downloadExport(jobId, kind === 'json' ? 'json' : kind);
}));
let _lastSingleId = null;
function lastCompletedSingleId() { return _lastSingleId; }

/* 批量页绑定 */
$('#batchRun').addEventListener('click', runBatch);
$('#batchCancel').addEventListener('click', async () => {
  if (state.batchJobId) { try { await api('POST', '/api/jobs/' + state.batchJobId + '/cancel'); } catch (e) {} }
});
$$('#batchPager button').forEach(b => b.addEventListener('click', () => {
  if (!/^\d+$/.test(b.textContent)) return;
  $$('#batchPager button').forEach(x => x.classList.remove('on')); b.classList.add('on');
}));

/* 扫描页绑定 */
$$('#scanAxis button').forEach(b => b.addEventListener('click', () => {
  $$('#scanAxis button').forEach(x => x.classList.remove('on')); b.classList.add('on');
  state.scan.axis = b.dataset.v;
  if (state.scan.axis === 'te') { $('#scanFrom').value = 0.6; $('#scanTo').value = 1.8; }
  if (state.scan.axis === 'ne') { $('#scanFrom').value = 15; $('#scanTo').value = 18; }
  if (state.scan.axis === 'r') { $('#scanFrom').value = 1000; $('#scanTo').value = 10000; }
  renderScanVals();
}));
['scanFrom', 'scanTo', 'scanFrames'].forEach(id => $('#'+id).addEventListener('input', () => {
  $('#framesVal').textContent = $('#scanFrames').value;
  renderScanVals();
}));
$('#previewScan').addEventListener('click', () => { renderScanVals(); toast('ok', '扫描值已预览', '确切采样值与 NIST 请求数量以提交后校验为准'); });
$('#scanRun').addEventListener('click', runScan);
$('#scanCancel').addEventListener('click', async () => {
  if (state.currentJob) { try { await api('POST', '/api/jobs/' + state.currentJob.id + '/cancel'); } catch (e) {} }
});
$('#playBtn').addEventListener('click', scanPlayToggle);
$('#framePrev').addEventListener('click', () => { if (state.scan.playing) scanPlayToggle(); scanSetFrame(state.scan.frame - 1); });
$('#frameNext').addEventListener('click', () => { if (state.scan.playing) scanPlayToggle(); scanSetFrame(state.scan.frame + 1); });
$('#scanSlider').addEventListener('input', e => { if (state.scan.playing) scanPlayToggle(); state.scan.frame = +e.target.value; drawScanFrame(); });
$('#gifBtn').addEventListener('click', () => {
  const jobId = _lastScanId;
  downloadExport(jobId, 'gif');
});
$('#framePngBtn').addEventListener('click', () => {
  if (!state.scanCache) return;
  downloadExport(_lastScanId, 'png', '&frame=' + state.scan.frame);
});
let _lastScanId = null;

/* 任务/设置页绑定 */
$('#jobsRefresh').addEventListener('click', loadJobs);
$('#saveSettings').addEventListener('click', saveSettings);
$('#reloadSettings').addEventListener('click', () => { loadSettings(true); toast('ok', '已还原', '重新读取已保存配置'); });

/* 图表交互绑定：框选放大 / 中键平移 / 右键复原 */
function redrawSpecInstant() {
  const A = getAnim(specCanvas);
  present(specCanvas, A.disp || specData, singleOpts || { views: state.views }, 'instant');
}
attachChartInteractions(specCanvas, redrawSpecInstant);
attachChartInteractions($('#scanChart'), () => drawScanFrame('instant'));

/* 窗口尺寸变化 */
window.addEventListener('resize', () => { if(state.hasResult)drawSingle(specData,true);else fetchPreview(); drawScanFrame('instant'); });

/* ================================================================
   启动
   ================================================================ */
(async function init() {
  renderComp();
  updateParamLabels();
  renderScanVals();
  drawEmpty($('#scanChart'), '扫描完成后可在此播放帧动画');
  try {
    const [st, params] = await Promise.all([api('GET', '/api/status'), api('GET', '/api/params')]);
    setOffline(false);
    applyStatus(st);
    if (params.params) {
      const p = params.params;
      $('#teSlider').value = p.te; $('#neSlider').value = Math.log10(p.ne); $('#rSlider').value = p.resolution;
      $('#lowW').value = p.low_w; $('#upW').value = p.up_w; $('#maxIon').value = p.max_ion_charge;
      state.mode = p.mode; $('#headless').checked = p.headless; $('#resample').checked = p.resample;
      $('#intensityScale').value=p.intensity_scale||'photon';
      if (p.broadening) {
        state.broadening = p.broadening;
        $('#broadenParams').hidden = p.broadening !== 'local';
        if (p.broaden_grid_step) $('#bGridStep').value = p.broaden_grid_step;
        if (p.broaden_min_rel_int != null) $('#bMinRel').value = p.broaden_min_rel_int;
      }
      $$('#modeSeg button').forEach(b => b.classList.toggle('on', b.dataset.v === p.mode));
      $$('#broadSeg button').forEach(b => b.classList.toggle('on', b.dataset.v === (p.broadening || 'nist')));
    }
    if (params.composition && params.composition.length) {
      state.comp = params.composition.map(c => ({ ...c }));
      renderComp();
    }
    if(params.element_symbols)elementMap=new Map(params.element_symbols.map(e=>[e.toLowerCase(),e]));
    if (params.title) $('#chartTitle').value = params.title;
    updateParamLabels();
    fetchPreview();
    loadJobs();
    loadSettings();
    // 恢复未完成任务
    const jobs = await api('GET', '/api/jobs');
    const active = jobs.jobs.find(j => !TERMINAL.includes(j.status));
    if (active) {
      state.batchJobId = active.job_id;
      attachJob(active.job_id, active.kind);
      setRunningUI(true);
      if (active.kind === '批量 dataset') { $('#batchLive').hidden = false; $('#batchJobId').textContent = active.job_id; }
    }
    // 记录最近成功任务，供导出按钮使用
    const lastSingle = jobs.jobs.find(j => j.kind === '单次模拟' && j.status === 'completed' && !j.mock_history);
    if (lastSingle) { _lastSingleId = lastSingle.job_id; _lastScanId = lastSingle.job_id; }
    const lastScan = jobs.jobs.find(j => j.kind === '扫描动画' && j.status === 'completed' && !j.mock_history);
    if (lastScan) _lastScanId = lastScan.job_id;
  } catch (e) {
    setOffline(true);
    updateParamLabels();
    drawSingle(localCalc(currentParams(), state.comp.map(c => c.el)));
  }
})();

/* finalize 时记录最近任务 id（导出按钮用） */
const _origFinalize = finalizeJob;
finalizeJob = async function (status) {
  return _origFinalize(status);
};
