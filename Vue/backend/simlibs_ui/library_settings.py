"""Service-owned local library configuration; library data is always read-only."""
from dataclasses import replace
from pathlib import Path
import sys
import os
from .settings import Settings


def load_service_settings(data):
    defaults = Settings()
    values = {key: value for key, value in data.items() if key in Settings.__dataclass_fields__}
    # Legacy line_database was an installation path, never an explicit override.
    override = data.get('line_database_override', '')
    if not isinstance(override, str):
        raise ValueError('本地谱线库覆写必须是字符串')
    values.update(source=defaults.source, python=sys.executable,
                  line_database_override=override,
                  line_database=override or defaults.line_database)
    # Missing custom media is reported by capabilities, not silently replaced here.
    return Settings(**values).validated()


def with_library_override(settings, value):
    if not isinstance(value, str):
        raise ValueError('本地谱线库路径必须是字符串')
    override = value.strip()
    if override and not Path(override).is_absolute():
        raise ValueError('本地谱线库须使用服务机器的绝对目录路径')
    directory = Path(override or Settings().line_database)
    if not directory.is_dir():
        raise ValueError(f'本地谱线库目录不存在：{directory}')
    # Check read access explicitly; inspect_library also validates CSV + metadata.
    with os.scandir(directory) as entries:
        next(entries, None)
    from .offline_database import capabilities
    report = capabilities(directory)
    if not report['ready']:
        raise ValueError('本地谱线库没有可用元素：' + str(report.get('error') or report.get('issues')))
    override = str(directory.resolve()) if override else ''
    return replace(settings, line_database_override=override,
                   line_database=override or Settings().line_database)
