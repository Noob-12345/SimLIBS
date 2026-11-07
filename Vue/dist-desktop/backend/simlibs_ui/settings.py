"""显式设置和 JSON 配置，读取配置不会联网。"""
from dataclasses import asdict, dataclass, replace
from pathlib import Path
import json
import os
import sys
from .models import Parameters, finite

UI_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON = os.environ.get('SIMLIBS_UI_PYTHON') or next(
    (path for path in (r'E:\Anaconda\envs\simLIBS\python.exe',
                       r'D:\Anaconda3\envs\simLIBS\python.exe') if Path(path).is_file()),
    sys.executable)
DEFAULT_SOURCE = str(UI_ROOT / 'source')


@dataclass(frozen=True)
class Settings:
    python: str = DEFAULT_PYTHON
    source: str = DEFAULT_SOURCE
    line_database: str = str(UI_ROOT/'Linedatabase')
    driver: str = ''
    chrome: str = ''
    output: str = os.environ.get('SIMLIBS_OUTPUT', str(UI_ROOT.parent / 'outputs'))
    connect_timeout: float = 10
    read_timeout: float = 30
    page_timeout: float = 45
    script_timeout: float = 15
    static_deadline: float = 60
    dynamic_deadline: float = 180
    tls_verify: bool = True
    line_database_override: str = ''

    def validated(self):
        if not Path(self.python).is_file():
            raise ValueError(f'解释器不存在：{self.python}')
        if not (Path(self.source) / 'simLIBS' / 'simulation.py').is_file():
            raise ValueError(f'源目录必须包含 simLIBS/simulation.py：{self.source}')
        for key in ('driver', 'chrome'):
            value = getattr(self, key)
            if value and not Path(value).is_file():
                raise ValueError(f'{key} 路径不存在：{value}')
        if not str(self.output).strip():
            raise ValueError('输出目录不能为空')
        if type(self.tls_verify) is not bool:
            raise ValueError('TLS 校验必须是布尔值')
        names = ('connect_timeout', 'read_timeout', 'page_timeout', 'script_timeout', 'static_deadline', 'dynamic_deadline')
        values = {k: finite(getattr(self, k), k, True) for k in names}
        if any(v > 3600 for v in values.values()):
            raise ValueError('超时不能超过 3600 秒')
        return replace(self, **values)

    def to_dict(self):
        return asdict(self)


PRESETS = {
    'H 窄波段（已验证参数）': Parameters(),
    'W/Fe/Mo（源库 README）': Parameters(elements=('W', 'Fe', 'Mo'), percentages=(50, 25, 25), low_w=200, upper_w=1000),
}


def save_config(path, settings, parameters, extra=None):
    from .storage import write_json
    write_json(path, {'schema': 1, 'settings': settings.validated().to_dict(),
                      'parameters': parameters.validated().to_dict(), 'extra': extra or {}})


def load_config(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if data.get('schema') != 1:
            raise ValueError('不支持的配置 schema（需要 1）')
        return Settings(**data['settings']).validated(), Parameters.from_dict(data['parameters']), data.get('extra', {})
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f'无法读取配置：{exc}') from exc
