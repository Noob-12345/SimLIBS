# simLIBS Web UI

本目录提供 HTML/CSS/JavaScript 光谱界面和 Python 计算后台，根据元素原子百分比、电子温度 Te、电子密度 Ne 与分辨率 R 生成可追溯的 LIBS 光谱，支持单次模拟、批量模拟、参数扫描及训练数据 ZIP 导出。详细功能、计算约定和接口见 [web/README.md](web/README.md)。

## 启动

双击 `web/start_web.cmd`，或在 PowerShell 中运行：

```powershell
& 'D:\LIBS\SimLIBS\UI\web\start_web.cmd'
# 不自动打开浏览器：
& 'E:\Anaconda\envs\simLIBS\python.exe' -B 'D:\LIBS\SimLIBS\UI\web\server.py' --port 8517 --no-browser
```

打开 `http://127.0.0.1:8517/`。启动器优先使用 `SIMLIBS_UI_PYTHON` 显式指定的已有 Python 3.10+ 解释器；其次使用现有 E 盘环境，并兼容仍存在的旧 D 盘环境。无需安装新依赖。直接打开 HTML 文件仅进入明确标注的离线示意模式，实际模拟需启动 Python 后台。

## 目录用途

| 路径 | 用途 |
|---|---|
| `web/static/` | HTML 页面、样式、Canvas 全量节点绘制与元素贡献交互 |
| `web/server.py` | 本地 HTTP/API/SSE 服务 |
| `web/real_backend.py` | Web 请求、后台任务和完整结果的接口适配 |
| `simlibs_ui/` | 共享计算模型、NIST 适配、worker/进程生命周期、存储及 CSV/PNG/GIF/训练包导出 |
| `tests/` | 后台、接口和隔离浏览器回归 |
| `output/` | 已有任务、完整科学结果及来源证据 |
| `.driver-cache/` | 已有 ChromeDriver 缓存 |
| `.ai-workflow/` | 历史方案、实现与独立验收记录 |

Python 文件属于 Web 计算后台，并非因为界面使用 HTML 就可删除。桌面启动器和 tkinter 专属应用已移除；源库 `../simLIBS-2.0.3`、参考训练项目和已有结果保持只读或原样保留。

## 计算与验证

新版请求使用 `server/client`、`mode_version=2`：服务器模式读取 NIST 数据并执行官方浏览器 JavaScript Recalculate；客户端从 NIST 未展宽线表分段合并后 Python 统一合成，无需 Chrome。Web 传递实际完整 CSV 节点，提供真实元素贡献和按帧扫描；旧 `static/dynamic` 请求及历史来源继续原语义。NIST、历史 CSV 与 MOCK 来源明确区分，失败/取消保留上一成功结果。

```powershell
& 'E:\Anaconda\envs\simLIBS\python.exe' -B -m unittest discover -s tests -p 'test_*.py' -v
```

默认回归不运行新 NIST 模拟，隔离浏览器测试通过显式开关单独启用；详细说明见 Web README 和 `.ai-workflow` 中对应验收材料。
