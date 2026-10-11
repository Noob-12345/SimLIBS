"""桥接真实引擎测试（local 离线模式，不联网）：单次/扫描/批量 + 全部离线导出。

用法：
    E:/Anaconda/envs/simLIBS/python.exe -B tests/test_bridge_real_local.py
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
            [PYTHON, '-B', str(ROOT / 'backend' / 'wpf_bridge.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(ROOT), encoding='utf-8')
        self._lock = threading.Lock()
        self._next_id = 0
        self._responses: dict[int, dict] = {}
        self.events: list[dict] = []
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self) -> None:
        for line in self.proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if 'event' in message:
                self.events.append(message)
                if message['event'] == 'bridge_log' and message.get('level') == 'error':
                    print('  [bridge-error]', message.get('message', '')[:200])
            else:
                self._responses[message.get('id')] = message

    def send(self, cmd: str, data: dict | None = None, timeout: float = 60.0) -> dict:
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

    def run_job(self, kind: str, body: dict, timeout: float = 300.0) -> str:
        r = self.send(f'start_{kind}', body, timeout=30)
        if not r['ok']:
            raise RuntimeError(f"start_{kind} 失败：{r.get('error')}")
        job_id = r['data']['job_id']
        self.send('subscribe', {'job_id': job_id})
        final = self.wait_event(lambda m: m['event'] == 'job_event' and m['job_id'] == job_id
                                and m['data'].get('final'), timeout=timeout)
        status = final['data'].get('status')
        if status != 'completed':
            raise RuntimeError(f'任务终态 {status} · {final["data"].get("message", "")}')
        return job_id

    def wait_event(self, predicate, timeout: float = 60.0) -> dict:
        deadline = time.time() + timeout
        seen = 0
        while time.time() < deadline:
            events = self.events
            for message in events[seen:]:
                if predicate(message):
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
        ready = bridge.wait_event(lambda m: m['event'] == 'ready', timeout=120)
        check('ready（真实引擎）', ready['data']['mock'] is False)
        print('  解释器:', ready['data']['interpreter'])

        r = bridge.send('engine_status', {'mode': 'local'})
        local_caps = r['data'].get('local') or {}
        check('线库就绪', r['ok'] and local_caps.get('ready') is True,
              json.dumps(local_caps, ensure_ascii=False)[:200])
        if not local_caps.get('ready'):
            print('线库不可用，跳过真实测试')
            return 1

        r = bridge.send('default_params')
        defaults = r['data']
        check('default_params(local v2)', defaults['params']['mode'] == 'local'
              and defaults['params']['mode_version'] == 2)
        params = dict(defaults['params'])
        params['broaden_grid_step'] = 0.01
        comp = defaults['composition']          # Fe 100%
        check('默认组成 Fe', comp[0]['el'] == 'Fe' and comp[0]['pct'] == 100)

        # settings 读写往返
        r = bridge.send('get_settings')
        saved = {k: v for k, v in r['data'].items()}
        r = bridge.send('save_settings', saved)
        check('save_settings 往返', r['ok'] and r['data']['python'] == saved['python'],
              r.get('error', {}).get('message', ''))

        # 单次（未展宽线谱，30k 点量级）
        job_id = bridge.run_job('single', {'params': params, 'composition': comp,
                                           'title': 'WPF 真实冒烟'})
        r = bridge.send('get_result', {'job_id': job_id})
        result = r['data']
        check('真实单次出谱', r['ok'] and result['kind'] == 'single'
              and len(result['xs']) > 1000, f"点数 {len(result.get('xs', []))}")
        check('真实单次 meta', bool(result['meta'].get('computation_location'))
              and 'ion' in json.dumps(result['meta'].get('ions', []), ensure_ascii=False).lower()
              or bool(result['meta'].get('ions')))
        for kind in ('csv', 'png', 'json'):
            r = bridge.send('export', {'job_id': job_id, 'kind': kind}, timeout=120)
            check(f'导出 {kind}', r['ok'] and (r['data']['b64'] or r['data']['text']),
                  r.get('error', {}).get('message', ''))

        # 扫描（3 帧）
        scan_id = bridge.run_job('scan', {'params': params, 'composition': comp,
                                          'axis': 'te', 'start': 0.9, 'end': 1.1, 'frames': 3})
        r = bridge.send('get_result', {'job_id': scan_id})
        check('真实扫描帧表', r['ok'] and r['data']['kind'] == 'scan'
              and len(r['data']['frames']) == 3)
        r = bridge.send('get_result', {'job_id': scan_id, 'frame': 2}, timeout=120)
        check('真实扫描懒帧', r['ok'] and r['data'].get('frame') == 2
              and len(r['data']['xs']) > 100, r.get('error', {}).get('message', ''))
        r = bridge.send('export', {'job_id': scan_id, 'kind': 'gif'}, timeout=180)
        check('真实扫描 GIF', r['ok'] and r['data']['b64'], r.get('error', {}).get('message', ''))

        # 批量（随机规则 3 样本，Fe 随机 + Mo 固定）
        rule = {'kind': 'random',
                'te': {'enabled': True, 'min': 0.9, 'max': 1.2},
                'ne': {'enabled': True, 'min': 1e17, 'max': 5e17},
                'concentrations': [{'el': 'Fe', 'enabled': True, 'min': 60, 'max': 85},
                                   {'el': 'Mo', 'enabled': False, 'fixed': 15}]}
        batch_body = {'params': params, 'n_samples': 3, 'seed': 7, 'batch_size': 2,
                      'te_range': [0.9, 1.2], 'ne_range': [17, 17.7], 'generation': rule}
        batch_id = bridge.run_job('batch', batch_body, timeout=600)
        r = bridge.send('get_result', {'job_id': batch_id}, timeout=120)
        batch = r['data']
        check('真实批量结果', r['ok'] and batch['kind'] == 'batch'
              and batch['summary']['completed'] == 3, json.dumps(batch.get('summary', {})))
        check('真实训练包就绪', batch.get('training_package', {}).get('available') is True,
              json.dumps(batch.get('training_package', {}), ensure_ascii=False)[:200])
        for kind in ('dataset', 'training', 'parameters', 'template'):
            r = bridge.send('export', {'job_id': batch_id, 'kind': kind}, timeout=180)
            check(f'批量导出 {kind}', r['ok'] and (r['data']['b64'] or r['data']['text']),
                  r.get('error', {}).get('message', ''))

        # 校验错误路径：server 模式 R<100
        bad = dict(params)
        bad.update(mode='server', mode_version=2, broadening='nist', resolution=50)
        r = bridge.send('start_single', {'params': bad, 'composition': comp})
        check('server R<100 拦截', not r['ok'] and 'R>=100' in r['error']['message'],
              json.dumps(r.get('error', {}), ensure_ascii=False))
    finally:
        bridge.close()

    print(f"\n通过 {len(PASS)} · 失败 {len(FAIL)}")
    if FAIL:
        print('失败项：', '、'.join(FAIL))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
