"""只在任务进程内修补传输和浏览器；保留原构造、解析和科学插值。"""
from contextlib import ExitStack
import hashlib
import importlib
import io
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.driver_cache import DriverCacheManager
from webdriver_manager.core.os_manager import OperationSystemManager, ChromeType
from .settings import UI_ROOT
from .models import MAX_POINTS
from .storage import clean_spectrum, now
from . import nist_recon


def source_module(source):
    source = Path(source).resolve()
    expected = source / 'simLIBS' / 'simulation.py'
    if not expected.is_file():
        raise ValueError(f'源文件不存在：{expected}')
    sys.dont_write_bytecode = True
    current = sys.modules.get('simLIBS.simulation')
    if current is not None and Path(current.__file__).resolve() != expected:
        raise RuntimeError('本进程已加载另一源目录；更改源目录后请启动新任务')
    added = str(source) not in sys.path
    if added:
        sys.path.insert(0, str(source))
    try:
        module = importlib.import_module('simLIBS.simulation')
    finally:
        if added:
            sys.path.remove(str(source))
    if Path(module.__file__).resolve() != expected:
        raise RuntimeError(f'源导入定位错误：{module.__file__}')
    return module


def chrome_version(settings):
    # 指定 Chrome 时读取文件版本，避免执行 chrome.exe 打开用户会话。
    if settings.chrome and sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        version = ctypes.windll.version
        unused = wintypes.DWORD()
        size = version.GetFileVersionInfoSizeW(settings.chrome, ctypes.byref(unused))
        buffer = ctypes.create_string_buffer(size)
        if size and version.GetFileVersionInfoW(settings.chrome, 0, size, buffer):
            ptr, length = ctypes.c_void_p(), wintypes.UINT()
            if version.VerQueryValueW(buffer, '\\', ctypes.byref(ptr), ctypes.byref(length)):
                fields = ctypes.cast(ptr, ctypes.POINTER(wintypes.DWORD))
                return '.'.join(str(x) for x in (fields[2] >> 16, fields[2] & 65535, fields[3] >> 16, fields[3] & 65535))
        raise RuntimeError(f'无法读取 Chrome 文件版本：{settings.chrome}')
    value = OperationSystemManager().get_browser_version_from_os(ChromeType.GOOGLE)
    if not value:
        raise RuntimeError('未发现 Chrome；请在设置中填写 chrome.exe 路径')
    # manager 通常仅返回 major.minor.build，保留注册表完整版本用于匹配下载。
    if sys.platform == 'win32':
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r'Software\Google\Chrome\BLBeacon') as key:
                    full = winreg.QueryValueEx(key, 'version')[0]
                    if full.startswith(value):
                        return full
            except OSError:
                pass
    return value


def driver_version(path):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    result = subprocess.run([str(path), '--version'], capture_output=True, text=True, timeout=10, creationflags=flags)
    match = re.search(r'ChromeDriver\s+(\d+(?:\.\d+)+)', result.stdout)
    if result.returncode or not match:
        raise RuntimeError(f'无法读取 ChromeDriver 版本：{path}；{result.stderr[:300]}')
    return match.group(1)


def resolve_driver(settings):
    browser = chrome_version(settings)
    def matching(path):
        value = driver_version(path)
        if value.split('.')[:3] != browser.split('.')[:3]:
            raise RuntimeError(f'Chrome {browser} 与 ChromeDriver {value} 不匹配：{path}；请配置同版本驱动')
        return str(path), value
    if settings.driver:
        return matching(settings.driver)
    # 不使用源库随附驱动或不匹配缓存。只下载到 UI 所属缓存。
    try:
        manager = ChromeDriverManager(driver_version=browser, cache_manager=DriverCacheManager(root_dir=str(UI_ROOT / '.driver-cache')))
        path = manager.install()
        return matching(path)
    except Exception as exc:
        raise RuntimeError(f'Chrome {browser} 的匹配驱动获取失败：{exc}。后台 webdriver_manager 需要可用网络；可在设置中填写匹配 chromedriver.exe') from exc


def simulate(parameters, settings, cancelled=lambda:False, emit=None):
    p, s = parameters.validated(), settings.validated()
    if p.webscraping=='client':
        from .mode_engine import client_simulate
        return client_simulate(p,s,cancelled,emit)
    original_parameters=p
    if p.webscraping=='server':
        from dataclasses import replace
        p=replace(p,webscraping='dynamic',mode_version=1)
    module = source_module(s.source)
    source_file = Path(module.__file__).resolve()
    original_get = module.requests.get
    original_chrome = module.webdriver.Chrome
    original_service = module.Service
    diagnostics = Path(os.environ['SIMLIBS_TASK_DIR']) if os.environ.get('SIMLIBS_TASK_DIR') else None
    resolved = None
    options_seen = []
    captured = {}  # 最近一次 NIST 响应文本：实际 R 解析与本地线表展宽的数据源

    def bounded_get(url, **kwargs):
        kwargs.update(timeout=(s.connect_timeout, s.read_timeout), verify=s.tls_verify)
        response = original_get(url, **kwargs)
        response.raise_for_status()
        try:
            captured['html'] = response.text
        except Exception:
            pass
        return response

    class UIOptions(Options):
        def __init__(self):
            super().__init__()
            if p.headless:
                self.add_argument('--headless=new')
            if original_parameters.mode_version==2:
                # Chrome does not inherit HTTP(S)_PROXY like requests. Respect
                # the existing credential-free transport in this owned session only.
                from requests.utils import get_environ_proxies
                proxy=get_environ_proxies('https://physics.nist.gov/').get('https')
                if proxy and not urlsplit(proxy).username:
                    self.add_argument('--proxy-server='+proxy)
                self.set_capability('goog:loggingPrefs',{'performance':'ALL'})
            if s.chrome:
                self.binary_location = s.chrome
            options_seen.append(self)

    class DriverManager:
        def install(self):
            return resolved[0]

    class UIService(original_service):
        def __init__(self, *args, **kwargs):
            if diagnostics:
                kwargs.update(log_output=str(diagnostics/'chromedriver.log'), service_args=['--verbose'])
            super().__init__(*args, **kwargs)

    def chrome(*args, **kwargs):
        driver = original_chrome(*args, **kwargs)
        try:
            driver.set_page_load_timeout(s.page_timeout)
            driver.set_script_timeout(s.script_timeout)
            return driver
        except Exception:
            driver.quit()
            raise

    class UISimulation(module.SimulatedLIBS):
        def get_site(self):
            site=urlsplit(super().get_site())
            scale='1' if p.intensity_scale=='energy' else '2'
            min_rel = f'{p.broaden_min_rel_int:g}' if p.broadening == 'local' or original_parameters.mode_version==2 else None
            query=[]
            for key,value in parse_qsl(site.query,keep_blank_values=True):
                if key=='int_scale':
                    value=scale
                elif key=='min_rel_int' and min_rel is not None:
                    # 线表模式的选线阈值独立于源库默认 0.001（0 避免随波段选线漂移）
                    value=min_rel
                query.append((key,value))
            if not any(key=='int_scale' for key,_ in query):query.append(('int_scale',scale))
            return urlunsplit((site.scheme,site.netloc,site.path,urlencode(query),site.fragment))

        def _ui_local_render(self, html):
            """broadening='local'：解析未展宽线表 → 本地按官方约定展宽到合成网格。"""
            if not html:
                raise RuntimeError('未能获取 NIST 响应/页面文本；本地展宽需要 dataSticksArray 线表')
            sticks = nist_recon.parse_nist_matrix(html, 'dataSticksArray')
            nist_recon.line_strengths(sticks)  # 合法空表=空谱；非有限数值在此拒绝
            band = nist_recon.Band(core_low=float(p.low_w), core_high=float(p.upper_w))
            table = nist_recon.merge_core_sticks([sticks], [band])
            render_r = p.resolution * (2.0 * math.sqrt(2.0 * math.log(2.0))
                                       if p.broaden_convention == 'physics' else 1.0)
            n_points = int(round((float(p.upper_w) - float(p.low_w)) / p.broaden_grid_step)) + 1
            if n_points > MAX_POINTS:
                raise ValueError(f'本地合成网格 {n_points} 点超过 {MAX_POINTS} 上限')
            grid = np.linspace(float(p.low_w), float(p.upper_w), n_points)
            decimals = p.broaden_center_decimals if p.broaden_center_decimals is not None else None
            spectrum = nist_recon.render_nist_sticks(table, grid, render_r, center_decimals=decimals)
            return table, spectrum, render_r

        def _ui_ion_frame(self, table, render_r):
            """线表逐离子展宽 → ion DataFrame（Wavelength (nm) + 各离子 + Sum(calc)）。"""
            grid = self.raw_spectrum['wavelength'].to_numpy(dtype=float)
            decimals = p.broaden_center_decimals if p.broaden_center_decimals is not None else None
            return nist_recon.render_ion_sticks(table, grid, render_r, center_decimals=decimals)

        def _ui_line_table_file(self, table):
            if not diagnostics:
                return None
            path = diagnostics / 'line_table.csv'
            table.to_csv(path, index=False, encoding='utf-8-sig')
            return str(path)

        def interpolate(self, resolution=None):
            if p.broadening == 'local' and getattr(self, '_ui_local_table', None) is not None:
                # 本地展宽：合成谱已在展宽网格；"本地插值"开=再样条到 step 网格
                self.raw_spectrum = clean_spectrum(self.raw_spectrum)
                if len(self.raw_spectrum) < 2:
                    raise ValueError('插值至少需要两个不同波长点')
                if p.resample:
                    if math.ceil((self.upper_w - self.low_w) / p.step) > MAX_POINTS:
                        raise ValueError('构造插值网格超过 200000 点，未分配网格')
                    self.interpolated_spectrum = pd.DataFrame({'wavelength': [], 'intensity': []})
                    return super().interpolate(p.step)
                self.interpolated_spectrum = self.raw_spectrum.copy()
                return
            if resolution is None:
                resolution = p.step if p.resample else .005
            if math.ceil((self.upper_w-self.low_w)/resolution) > MAX_POINTS:
                raise ValueError('构造插值网格超过 200000 点，未分配网格')
            self.raw_spectrum = clean_spectrum(self.raw_spectrum)
            if len(self.raw_spectrum) < 2:
                raise ValueError('插值至少需要两个不同波长点')
            self.interpolated_spectrum = pd.DataFrame({'wavelength': [], 'intensity': []})
            return super().interpolate(resolution)

        def retrieve_data_static(self):
            if p.broadening == 'local':
                # 本地展宽：直接取响应解析线表（经 bounded_get 捕获），
                # 不依赖服务端 dataDopplerArray 解析成功。
                response = module.requests.get(self.get_site(), verify=False)
                captured['html'] = response.text
                table, spectrum, render_r = self._ui_local_render(captured['html'])
                self.raw_spectrum = spectrum
                self.ion_spectra = self._ui_ion_frame(table, render_r)
                self.ion_total = 'local: sum of per-ion reconstructed contributions'
                self._ui_local_table = table
                self._ui_render_r = render_r
                return
            super().retrieve_data_static()  # 原解析：dataDopplerArray（服务端展宽）

        def retrieve_data_dynamic(self):
            if p.broadening == 'local':
                # 客户端模式 + 本地展宽：服务端已按 URL 参数算好线表，
                # 直接读页面 JS 变量，无需 Recalculate/CSV。
                self.driver.get(self.get_site())
                captured['html'] = self.driver.page_source
                table, spectrum, render_r = self._ui_local_render(captured['html'])
                self.raw_spectrum = spectrum
                self.interpolated_spectrum = spectrum.copy()
                self.ion_spectra = self._ui_ion_frame(table, render_r)
                self.ion_total = 'local: sum of per-ion reconstructed contributions'
                self._ui_local_table = table
                self._ui_render_r = render_r
                return
            self.driver.get(self.get_site())
            captured['html'] = self.driver.page_source  # 供实际 R 解析
            if original_parameters.mode_version==2:
                from .mode_engine import RECALC_OBSERVER,browser_sources
                captured['browser_sources']=browser_sources(self.driver,self.get_site(),diagnostics)
                self.driver.execute_script(RECALC_OBSERVER)
            wait = WebDriverWait(self.driver, s.page_timeout)
            resolution = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input#resolution, input[name="resolution"]')))
            resolution.clear()
            resolution.send_keys(str(self.resolution))
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[name="recalc"]'))).click()
            if original_parameters.mode_version==2:
                runtime=wait.until(lambda driver:driver.execute_script('return window.__simlibsRecalculated'))
                if not runtime.get('rows') or not isinstance(runtime.get('effective_r'),(int,float)) or not math.isfinite(runtime['effective_r']) or runtime['effective_r']<=0:
                    raise ValueError('官方重算没有就绪的实际R/数据')
                captured['recalculated']=runtime
                if runtime['rows']>MAX_POINTS:raise ValueError('官方重算超过200000点生成上限，请缩小波段')
            old = set(self.driver.window_handles)
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[name="ViewDataCSV"], button[onclick*="viewDataCSV"]'))).click()
            # 某些页面复用已有 popup；优先新窗口，再用现有非主窗口。
            def csv_window(driver):
                handles = driver.window_handles
                return next((h for h in handles if h not in old), None) or (handles[-1] if len(handles) > 1 else False)
            self.driver.switch_to.window(wait.until(csv_window))
            pre = wait.until(EC.presence_of_element_located((By.TAG_NAME, 'pre')))
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            if not soup.pre:
                raise ValueError('NIST CSV 窗口缺少 pre 数据')
            # 不让 pandas 将真正空白与字面 NaN/Inf 混为缺失值；由清理层按列校验。
            csv_text = soup.pre.text
            if diagnostics:
                (diagnostics/'nist-dynamic.csv').write_text(csv_text, encoding='utf-8')
            csv_frame = pd.read_csv(io.StringIO(csv_text), dtype=str, keep_default_na=False)
            csv_columns = list(csv_frame.columns)
            self.ion_spectra = clean_spectrum(csv_frame, ion=True)
            self.ion_total = ('NIST Sum(calc)' if 'Sum(calc)' in csv_columns else
                              f'copied sole {next(c for c in csv_columns if c != "Wavelength (nm)")} contribution (NIST omitted Sum(calc))')
            raw = self.ion_spectra[['Wavelength (nm)', 'Sum(calc)']].rename(columns={'Wavelength (nm)': 'wavelength', 'Sum(calc)': 'intensity'})
            self.raw_spectrum = raw.copy()
            self.interpolated_spectrum = raw.copy()

    try:
        if p.webscraping == 'dynamic':
            resolved = resolve_driver(s)
        with ExitStack() as stack:
            stack.enter_context(patch.object(module.requests, 'get', bounded_get))
            stack.enter_context(patch.object(module, 'Options', UIOptions))
            stack.enter_context(patch.object(module, 'ChromeDriverManager', DriverManager))
            stack.enter_context(patch.object(module, 'Service', UIService))
            stack.enter_context(patch.object(module.webdriver, 'Chrome', chrome))
            elements, percentages = p.request_composition()
            # 原验证仅拒绝 >100，消除容差内的向上浮点残差（不更改保存配比）。
            if 100 < sum(percentages) <= 100 + 1e-6:
                percentages[-1] -= sum(percentages) - 100
            obj = UISimulation(Te=p.Te, Ne=p.Ne, elements=elements, percentages=percentages,
                               resolution=p.resolution, low_w=p.low_w, upper_w=p.upper_w,
                               max_ion_charge=p.max_ion_charge, webscraping=p.webscraping,
                               headless=p.headless, keep_browser_open=False, detach_browser=False)
            if p.resample and p.webscraping == 'dynamic' and original_parameters.mode_version==1:
                obj.interpolate(p.step)
            frames = {'raw': clean_spectrum(obj.get_raw_spectrum()),
                      'interpolated': clean_spectrum(obj.get_interpolated_spectrum())}
            if p.webscraping == 'dynamic' or p.broadening == 'local':
                # 源库 get_ion_spectra 只允许 dynamic；本地线表模式直接读属性
                ion_source = obj.get_ion_spectra() if p.webscraping == 'dynamic' else getattr(obj, 'ion_spectra', None)
                if ion_source is None:
                    raise RuntimeError('本地展宽未产生离子谱数据')
                frames['ion'] = clean_spectrum(ion_source, ion=True)
            actual_res = None
            if captured.get('html'):
                try:
                    actual_res = nist_recon.actual_resolution(captured['html'])
                except Exception:
                    actual_res = None
            origin = {'kind': 'simulation', 'label': '本次真实 NIST / SimulatedLIBS 模拟',
                      'class': 'simLIBS.simulation.SimulatedLIBS', 'source_file': str(source_file),
                      'source_sha256': hashlib.sha256(source_file.read_bytes()).hexdigest(),
                      'parameters': p.to_dict(), 'submitted_composition': dict(zip(elements, percentages)),
                      'actual_Ne': obj.Ne, 'nist_url': obj.get_site(), 'created_at': now(), 'tls_verify': s.tls_verify,
                      'intensity_scale':p.intensity_scale,'int_scale':1 if p.intensity_scale=='energy' else 2,
                      'intensity_units':'a.u. (relative flux, not absolute calibration)',
                      'driver_version': resolved[1] if resolved else None,
                      'browser_arguments': options_seen[0].arguments if options_seen else [],
                      'ion_total': getattr(obj, 'ion_total', None),
                      'ion_blank_policy': 'only explicit blank cells in valid ion contribution columns -> 0; missing wavelength/total and NaN/Inf rejected' if p.webscraping == 'dynamic' and p.broadening != 'local' else None,
                      'interpolation': 'source CubicSpline' if p.webscraping == 'static' or p.resample else 'NIST grid (raw = interpolated)'}
            origin.update({
                'computation_location': 'server' if p.webscraping == 'static' else 'client-js',
                'broadening': p.broadening,
                'actual_resolution': actual_res,
            })
            if p.broadening == 'local':
                origin['broadening_params'] = {
                    'convention': p.broaden_convention, 'grid_step': p.broaden_grid_step,
                    'center_decimals': p.broaden_center_decimals, 'min_rel_int': p.broaden_min_rel_int,
                    'render_resolution': getattr(obj, '_ui_render_r', None),
                }
                origin['interpolation'] = ('本地插值：CubicSpline → step 网格' if p.resample
                                           else '无（本地展宽合成网格即输出网格）')
                if getattr(obj, '_ui_local_table', None) is not None:
                    line_table_path = obj._ui_line_table_file(obj._ui_local_table)
                    if line_table_path:
                        origin['line_table'] = line_table_path
                        origin['line_table_rows'] = int(len(obj._ui_local_table))
            if actual_res is not None and p.broadening == 'nist' and abs(actual_res - p.resolution) > p.resolution * 0.02:
                origin['resolution_warning'] = (f'NIST 实际 R={actual_res:g}，低于请求 R={p.resolution:g}；'
                                                '谱线形状由实际 R 决定')
            if original_parameters.mode_version==2:
                from .mode_engine import finish_frames
                frames=finish_frames(original_parameters,frames['ion'])
                runtime=captured['recalculated']
                origin.update(parameters=original_parameters.to_dict(),mode='server',mode_version=2,
                              label='NIST 数据 + 官方 JS Recalculate（服务器模式 v2）',data_provider='NIST',
                              line_strength_location='official browser JavaScript',computation_location='official-browser-js',
                              initial_server_resolution=actual_res,actual_resolution=runtime['effective_r'],
                              requested_resolution=original_parameters.resolution,recalculation=runtime,
                              interpolation='linear on shared requested grid' if original_parameters.resample else 'none; complete official CSV')
                origin.update(browser_sources=captured['browser_sources'],official_js_sha256=captured['browser_sources']['official_js']['sha256'],
                              execution_environment='owned isolated Chrome; official lte_spectrum_js/Recalculate',
                              effective_resolution_source='official function return title built from its local effective resolution')
                origin.pop('resolution_warning',None)
                if runtime['effective_r']!=original_parameters.resolution:
                    origin['resolution_warning']=runtime['warning'] or f"官方重算受内存限制：实际 R={runtime['effective_r']}，请求 R={original_parameters.resolution}"
            return frames, origin
    except Exception as exc:
        driver_info = f'；ChromeDriver {resolved[1]} ({resolved[0]})' if resolved else ''
        raise RuntimeError(f'NIST {p.webscraping} 获取失败：{type(exc).__name__}: {exc}{driver_info}') from exc
