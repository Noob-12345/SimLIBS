"""桥接冒烟测试（--mock，不联网）：驱动 wpf_bridge.py 全命令收发。

用法：
    E:/Anaconda/envs/simLIBS/python.exe -B tests/test_bridge_mock.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = r'E:\Anaconda\envs\simLIBS\python.exe'
if not Path(PYTHON).is_file():
    PYTHON = sys.executable

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = '') -> None:
    (PASS if condition else FAIL).append(name)
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f"  {detail}" if detail and not condition else ''))


class Bridge:
    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [PYTHON, '-B', str(ROOT / 'backend' / 'wpf_bridge.py'), '--mock'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(ROOT), encoding='utf-8')
        self._lock = threading.Lock()
        self._next_id = 0
        self._responses: dict[int, dict] = {}
        self.events: list[dict] = []
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        for line in self.proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if 'event' in message:
                self.events.append(message)
            else:
                self._responses[message.get('id')] = message

    def send(self, cmd: str, data: dict | None = None, timeout: float = 30.0) -> dict:
        with self._lock:
            self._next_id += 1
            rid = self._next_id
            self.proc.stdin.write(json.dumps({'id': rid, 'cmd': cmd, 'data': data or {}}) + '\n')
            self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = self._responses.pop(rid, None)
            if message is not None:
                return message
            time.sleep(0.02)
        raise TimeoutError(f'{cmd} 超时')

    def wait_event(self, predicate, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        seen = 0
        while time.time() < deadline:
            events = self.events
            for message in events[seen:]:
                if predicate(message):
                    seen = events.index(message) + 1
                    return message
            seen = len(events)
            time.sleep(0.05)
        raise TimeoutError('等待事件超时')

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def main() -> int:
    bridge = Bridge()
    try:
        ready = bridge.wait_event(lambda m: m['event'] == 'ready', timeout=60)
        check('ready 握手', ready['data']['mock'] is True)

        r = bridge.send('hello')
        check('hello', r['ok'] and 'engine' in r['data'])

        r = bridge.send('default_params')
        check('default_params', r['ok'] and len(r['data']['element_symbols']) > 50,
              f"元素数 {len(r['data'].get('element_symbols', []))}")
        defaults = r['data']

        # v2 本地模式单次（C# 端主路径，mock 引擎应照常出谱）
        v2_params = {'te': 1.0, 'ne': 1e17, 'resolution': 5000, 'low_w': 400, 'up_w': 460,
                     'max_ion_charge': 2, 'mode': 'local', 'mode_version': 2, 'headless': True,
                     'resample': False, 'intensity_scale': 'photon', 'broadening': 'local',
                     'broaden_convention': 'physics', 'broaden_grid_step': 0.02,
                     'local_broadening_enabled': False}
        r = bridge.send('start_single', {'params': v2_params,
                                         'composition': [{'el': 'H', 'pct': 100}]})
        check('v2 local 单次启动', r['ok'], json.dumps(r.get('error', '')))
        v2_id = r['data']['job_id']
        bridge.send('subscribe', {'job_id': v2_id})
        bridge.wait_event(lambda m: m['event'] == 'job_event' and m['job_id'] == v2_id
                          and m['data'].get('final'), timeout=60)
        r = bridge.send('get_result', {'job_id': v2_id})
        check('v2 local 出谱', r['ok'] and len(r['data']['xs']) > 100,
              r.get('error', {}).get('message', ''))

        r = bridge.send('get_settings')
        check('get_settings', r['ok'] and 'python' in r['data'] and 'proxy' in r['data'])

        body = {'params': dict(defaults['params']), 'composition': defaults['composition'],
                'title': '桥接冒烟'}
        r = bridge.send('start_single', body)
        check('start_single', r['ok'], json.dumps(r.get('error', '')))
        job_id = r['data']['job_id']
        r = bridge.send('subscribe', {'job_id': job_id})
        check('subscribe', r['ok'])
        terminal = bridge.wait_event(
            lambda m: m['event'] == 'job_event' and m['job_id'] == job_id
            and m['data'].get('final'), timeout=60)
        check('单次终态事件', terminal['data'].get('status') == 'completed',
              terminal['data'].get('message', ''))

        r = bridge.send('get_result', {'job_id': job_id})
        result = r['data']
        check('单次结果 xs/ys', r['ok'] and result['kind'] == 'single'
              and len(result['xs']) == len(result['ys']) and len(result['xs']) > 100)
        check('单次 meta 基础字段', all(k in result['meta'] for k in
              ('source', 'points', 'duration')))

        r = bridge.send('export', {'job_id': job_id, 'kind': 'csv'})
        check('导出 CSV', r['ok'] and (r['data']['b64'] or r['data']['text']),
              r.get('error', {}).get('message', ''))
        r = bridge.send('export', {'job_id': job_id, 'kind': 'png'})
        check('导出 PNG', r['ok'] and r['data']['b64'], r.get('error', {}).get('message', ''))

        # 扫描（3 帧）
        scan_body = {'params': dict(defaults['params']), 'composition': defaults['composition'],
                     'axis': 'te', 'start': 0.8, 'end': 1.2, 'frames': 3}
        r = bridge.send('start_scan', scan_body)
        check('start_scan', r['ok'], json.dumps(r.get('error', '')))
        scan_id = r['data']['job_id']
        bridge.send('subscribe', {'job_id': scan_id})
        bridge.wait_event(lambda m: m['event'] == 'job_event' and m['job_id'] == scan_id
                          and m['data'].get('final'), timeout=60)
        r = bridge.send('get_result', {'job_id': scan_id})
        scan = r['data']
        check('扫描结果帧表', r['ok'] and scan['kind'] == 'scan' and len(scan['frames']) == 3)
        r = bridge.send('get_result', {'job_id': scan_id, 'frame': 1})
        data = r['data']
        check('扫描懒帧/整包回退', r['ok'] and (data.get('frame') == 1 and len(data['xs']) > 100
              or data.get('kind') == 'scan' and len(data.get('frames', [])) == 3))
        r = bridge.send('export', {'job_id': scan_id, 'kind': 'gif'})
        check('导出 GIF', r['ok'] and r['data']['b64'], r.get('error', {}).get('message', ''))

        # 批量（随机规则 3 样本）
        rule = {'kind': 'random',
                'te': {'enabled': True, 'min': 0.8, 'max': 1.4},
                'ne': {'enabled': True, 'min': 1e16, 'max': 1e18},
                'concentrations': [{'el': 'H', 'enabled': False, 'fixed': 60},
                                   {'el': 'Fe', 'enabled': True, 'min': 5, 'max': 40}]}
        batch_body = {'params': dict(defaults['params'], resample=True), 'n_samples': 3,
                      'seed': 7, 'batch_size': 2, 'te_range': [0.8, 1.4], 'ne_range': [16, 18],
                      'generation': rule}
        r = bridge.send('start_batch', batch_body)
        check('start_batch(随机)', r['ok'], json.dumps(r.get('error', '')))
        batch_id = r['data']['job_id']
        bridge.send('subscribe', {'job_id': batch_id})
        bridge.wait_event(lambda m: m['event'] == 'job_event' and m['job_id'] == batch_id
                          and m['data'].get('final'), timeout=90)
        r = bridge.send('get_result', {'job_id': batch_id})
        batch = r['data']
        check('批量结果', r['ok'] and batch['kind'] == 'batch'
              and batch['summary']['completed'] == 3, json.dumps(batch.get('summary', {})))
        # dataset/training/parameters/template 导出在 test_bridge_real_local.py 覆盖（mock 不提供）

        r = bridge.send('list_jobs')
        check('list_jobs', r['ok'] and len(r['data']['jobs']) >= 4,
              f"任务数 {len(r['data'].get('jobs', []))}")

        # 校验错误路径：配比不为 100%
        bad = {'params': dict(defaults['params']),
               'composition': [{'el': 'H', 'pct': 50}], 'title': 'bad'}
        r = bridge.send('start_single', bad)
        check('配比校验拦截', not r['ok'] and '100%' in r['error']['message'])

        # 历史 CSV 离线打开
        history = ROOT / 'tests' / '_tmp_history.csv'
        history.write_text('wavelength,intensity\n650.0,10\n650.5,90\n651.0,20\n', encoding='utf-8')
        r = bridge.send('open_history', {'path': str(history)})
        check('open_history', r['ok'] and len(r['data']['series'][0]['xs']) == 3,
              r.get('error', {}).get('message', ''))
        history.unlink(missing_ok=True)

        # 错误路径：无效命令
        r = bridge.send('no_such_cmd')
        check('未知命令报错', not r['ok'] and r['error']['code'] == 'unknown_cmd')
    finally:
        bridge.close()

    print(f"\n通过 {len(PASS)} · 失败 {len(FAIL)}")
    if FAIL:
        print('失败项：', '、'.join(FAIL))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
