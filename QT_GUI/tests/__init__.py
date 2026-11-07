"""CLI 测试包：把 CLI 根目录与 UI 后端路径注入 sys.path（与 run_cli.py 一致）。"""
import sys
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[1]
for p in (str(CLI_ROOT), str(CLI_ROOT / 'simlibs_cli')):
    if p not in sys.path:
        sys.path.insert(0, p)

import simlibs_cli.backend as backend_mod  # noqa: E402  (导入即注入 UI/web 路径)
