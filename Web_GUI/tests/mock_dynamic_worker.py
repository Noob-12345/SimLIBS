"""离线测试 worker：保留真实任务/源库路径，仅替换 Selenium 传输。"""
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch
from simlibs_ui.adapter import source_module
from simlibs_ui.settings import Settings
from simlibs_ui.storage import write_json
from simlibs_ui.worker import main

request_path = Path(sys.argv[1])
request = json.loads(request_path.read_text(encoding='utf-8'))
module = source_module(Settings(**request['settings']).source)
driver = Mock()
driver.window_handles = ['main', 'csv']
driver.page_source = '<html><pre>' + request['csv'] + '</pre></html>'
driver.find_element.return_value.is_displayed.return_value = True
driver.find_element.return_value.is_enabled.return_value = True
with patch('simlibs_ui.adapter.resolve_driver', return_value=('mock.exe', '154.0.8037.92')), \
     patch.object(module.webdriver, 'Chrome', return_value=driver):
    exit_code = main()
write_json(request_path.parent/'mock-browser.json', {'quit_count': driver.quit.call_count})
raise SystemExit(exit_code)
