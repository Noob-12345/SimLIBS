"""Bounded, read-only runtime evidence. Never installs or probes the network."""
import contextlib
from datetime import datetime, timezone
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import threading

# These imports are used by the existing worker/adapter and export paths.
# Import names deliberately differ from pip distribution names where required.
DEPENDENCIES = (
    ('numpy', 'numpy', '任务初始化与数值计算'),
    ('pandas', 'pandas', '任务初始化与数据表'),
    ('scipy.special', 'scipy', '本地展宽'),
    ('scipy.interpolate', 'scipy', '引擎初始化与插值'),
    ('scipy.integrate', 'scipy', '高级自吸收积分'),
    ('requests', 'requests', '引擎初始化与在线请求'),
    ('bs4', 'beautifulsoup4', '适配器初始化与网页解析'),
    ('selenium.webdriver', 'selenium', '适配器初始化；未启动浏览器'),
    ('webdriver_manager.chrome', 'webdriver-manager', '适配器初始化；未下载驱动'),
    ('matplotlib.figure', 'matplotlib', '引擎初始化与图像导出'),
    ('matplotlib.backends.backend_agg', 'matplotlib', '无界面图像导出'),
    ('PIL.Image', 'Pillow', '图像与动画导出'),
)
_lock = threading.Lock()


def safe_message(error):
    text = str(error)
    secret = os.environ.get('SIMLIBS_SESSION_TOKEN', '')
    if secret:
        text = text.replace(secret, '[已隐藏凭证]')
    text = re.sub(r'(?i)(token|authorization|password)([\s:=\"\']+)[^\s,;]+', r'\1=[已隐藏]', text)
    text = re.sub(r'(?i)\b[0-9a-f]{32,}\b', '[已隐藏]', text)
    return re.sub(r'[\x00-\x1f\x7f]', ' ', text)[:240]


def probe_imports(importer=importlib.import_module):
    checks = []
    for module, distribution, affected in DEPENDENCIES:
        try:
            with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                importer(module)
            try:
                version = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                version = '版本元数据不可用'
            checks.append(dict(module=module, distribution=distribution, state='ok', summary='导入通过 · ' + version, affected=affected))
        except Exception as error:
            checks.append(dict(module=module, distribution=distribution, state='error', summary=type(error).__name__ + ': ' + safe_message(error), affected=affected))
    return checks


def dependency_evidence(runner=subprocess.run):
    if not _lock.acquire(blocking=False):
        return dict(state='checking', checks=[], summary='另一次依赖检查正在执行，请稍后重新检查')
    try:
        options = dict(capture_output=True, text=True, encoding='utf-8', timeout=18, check=False,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', MPLBACKEND='Agg'))
        if os.name == 'nt':
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
        child = runner([sys.executable, '-B', str(Path(__file__).resolve()), '--imports'], **options)
        if child.returncode:
            return dict(state='unknown', checks=[], summary='依赖检查子进程未正常完成；未采用其日志作为就绪证据')
        checks = json.loads(child.stdout)
        if not isinstance(checks, list) or len(checks) != len(DEPENDENCIES):
            raise ValueError('依赖检查结果不完整')
        return dict(state='error' if any(item['state'] != 'ok' for item in checks) else 'ok', checks=checks,
                    summary='逐项导入检查；不代表模拟正确性或在线服务可用性')
    except subprocess.TimeoutExpired:
        return dict(state='unknown', checks=[], summary='依赖导入检查超过18秒，已停止该检查子进程；请检查解释器或安全软件后重试')
    except (OSError, ValueError, KeyError, TypeError):
        return dict(state='unknown', checks=[], summary='无法取得完整依赖导入证据，请检查所选 Python 后重新检查')
    finally:
        _lock.release()


def library_evidence(local):
    local = local or {}
    issues = local.get('issues') or {}
    evidence = [safe_message(local['error'])] if local.get('error') else []
    evidence += [safe_message(el + ': ' + '；'.join(errors)) for el, errors in list(issues.items())[:8]]
    ready = local.get('ready') is True and bool(local.get('elements'))
    state = 'error' if not ready else 'warning' if evidence else 'ok'
    return dict(state=state, summary=f"{len(local.get('elements') or [])} 个可用元素 · {local.get('csv_count', 0)} 个 CSV",
                root=local.get('root', ''), evidence=evidence,
                guidance='请恢复本程序 backend/Linedatabase 中缺失或损坏的谱线与静态元数据，然后重新检查；不要用空文件代替。' if state != 'ok' else '仅验证现有本地谱库；元素/离子覆盖范围以实际任务预检为准。')


def inspect_runtime(local, settings):
    return dict(schema=1, checked_at=datetime.now(timezone.utc).isoformat(),
                interpreter=dict(executable=sys.executable, version=platform.python_version(), worker_executable=settings.get('python', '')),
                dependencies=dependency_evidence(), local=library_evidence(local),
                online=dict(state='unknown', summary='未检测 NIST 连通性、Chrome 或驱动版本匹配；本地模式无需这些在线条件。',
                            guidance='需要在线模式时，可在设置中配置匹配的浏览器驱动；本次检查不启动浏览器、不下载驱动、不访问 NIST。'))


if __name__ == '__main__' and sys.argv[1:] == ['--imports']:
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(probe_imports(), ensure_ascii=False))
