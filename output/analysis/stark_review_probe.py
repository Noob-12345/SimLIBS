"""Independent offline probes; only temporary data and review artifacts are written."""
import contextlib
import copy
import base64
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2] / 'simLIBS-2.0.3'
sys.path.insert(0, str(ROOT))
import stark_data_collect as collector
import stark_html_collect as html_collector
from bs4 import BeautifulSoup
from simLIBS.stark_b import evaluate_width, StarkBUnavailable
from simLIBS.stark_resolver import load_database

spec = importlib.util.spec_from_file_location('_review_fixture', ROOT / 'tests/test_stark_data_collect.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def export_load_probe():
    test = fixture.StarkDataCollectTests()
    test.setUp()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            test.fetch()
            output = test.directory / 'stark_broadening.json'
            test.collector.export_stark_database(test.directory, output)
        doc = test.read(output)
        result = {'rows_sha256': doc['rows_sha256'], 'complete': doc['complete']}
        stored = doc['raw_payloads'][0]
        if stored.get('encoding') == 'gzip+base64':
            raw = gzip.decompress(base64.b64decode(stored['payload_gzip_base64'], validate=True))
            original = test.read(test.directory/doc['manifest']['species'][0]['path'])['payload']
            result['compressed_payload'] = dict(
                sha256_matches=hashlib.sha256(raw).hexdigest() == stored['uncompressed_sha256'],
                exact_payload_json_bytes_match=raw == test.collector._json_bytes(original),
                decoded_payload_matches=json.loads(raw) == original)
        try:
            load_database(output)
            result['load'] = 'accepted'
        except Exception as exc:
            result['load'] = type(exc).__name__ + ': ' + str(exc)
        return result
    finally:
        test.doCleanups()


def nonpositive_probe():
    result = {}
    client = collector._client()
    for filename, element, charge in [('Cl_q6_probe.xml', 'Cl', 6),
                                      ('Mg_q10_probe.xml', 'Mg', 10),
                                      ('ca_probe.xml', 'Ca', 8)]:
        payload = dict(format='vamdc-xsams', pages=[dict(
            xml=(ROOT/'stark-b/diagnostics'/filename).read_text(encoding='utf-8'),
            url=client.TAP_URL, headers={'VAMDC-TRUNCATED': 'None'})])
        rows = client.parse_payload(payload, element=element, charge=charge, ne=1e-300)
        bad = []
        for row in rows:
            for sample in row['samples']:
                if sample['fwhm_angstrom'] > 0:
                    continue
                try:
                    evaluate_width(row, temperature_k=sample['temperature_k'], ne=sample['ne'],
                                   wavelength_nm=row['calculated_wavelength_angstrom']/10)
                    status = 'ACCEPTED'
                except StarkBUnavailable:
                    status = 'rejected'
                bad.append(dict(width=sample['fwhm_angstrom'], flag=sample['flag'], status=status))
        result[filename] = dict(rows=len(rows), samples=sum(len(r['samples']) for r in rows), nonpositive=bad)
    return result


def html_probe():
    payload = json.loads((ROOT/'stark-b/diagnostics/pb_official_payload.json').read_bytes())
    rows = html_collector.parse_payload(payload, element='Pb', charge=3, ne=1e-300)
    result = {'pages': len(payload['pages']), 'tables': len(rows),
              'samples': sum(len(r['samples']) for r in rows),
              'dataset_densities': [(p['dataset_id'], p['ne']) for p in payload['pages']]}
    bad = copy.deepcopy(payload)
    for page in bad['pages']:
        if page['dataset_id'] == '129':
            soup = BeautifulSoup(page['html'], 'html.parser')
            for tr in soup.select('#shiftings tbody tr'):
                tr.decompose()
            page['html'] = str(soup)
    reduced = collector._payload_rows(collector._client(), bad, 'Pb', 3)
    result['empty_dataset_accepted'] = dict(tables=len(reduced), status=bad['status'],
                                          dataset_ids=sorted({r['dataset_id'] for r in reduced}))
    test = fixture.StarkDataCollectTests()
    test.setUp()
    try:
        test.service.species = [('Pb', 3)]
        test.service.fetch_species = lambda element, charge, ne: copy.deepcopy(bad)
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = test.fetch()
            output = test.directory/'stark_broadening.json'
            exported = test.collector.export_stark_database(test.directory, output)
        result['empty_dataset_collection'] = dict(complete=manifest['complete'], counts=manifest['counts'],
                                                  exported_complete=exported['complete'])
    finally:
        test.doCleanups()
    return result


def malformed_probe():
    html = (ROOT/'tests/fixtures/starkb_si_ii_6347.html').read_text(encoding='utf-8')
    result = {}
    for case in ['zero_temperature', 'negative_temperature', 'zero_wavelength', 'duplicate_temperature']:
        soup = BeautifulSoup(html, 'html.parser')
        first = soup.select('#shiftings tbody tr')[0]
        if case == 'zero_temperature':
            first.find_all('td')[6].string = '0'
        elif case == 'negative_temperature':
            first.find_all('td')[6].string = '-5000'
        elif case == 'zero_wavelength':
            for tr in soup.select('#shiftings tbody tr'):
                tr.find_all('td')[4].string = '0'
        else:
            duplicate = copy.deepcopy(first)
            duplicate.find_all('td')[9].string = '1000'
            first.insert_after(duplicate)
        payload = dict(format='starkb-html', pages=[dict(
            html=str(soup), url='https://stark-b.obspm.fr/index.php/data/ion/14',
            dataset_id='fixture', method='SCP', ne=1e17)])
        try:
            row, = html_collector.parse_payload(payload, element='Si', charge=1, ne=1e-300)
            result[case] = dict(accepted=True, samples=len(row['samples']))
            if case == 'duplicate_temperature':
                result[case]['conflicting_widths'] = [s['fwhm_angstrom'] for s in row['samples']
                                                       if s['temperature_k'] == 5000]
                result[case]['selected_renderer_hwhm_nm'] = evaluate_width(
                    row, temperature_k=5000, ne=1e17, wavelength_nm=634.7)['stark_width_nm']
        except Exception as exc:
            result[case] = dict(accepted=False, error=repr(exc))
    return result


if __name__ == '__main__':
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')), \
         patch('socket.create_connection', side_effect=AssertionError('Network forbidden')):
        result = dict(export_load=export_load_probe(), nonpositive=nonpositive_probe(),
                      html=html_probe(), malformed=malformed_probe())
    sources = ['stark_data_collect.py', 'stark_html_collect.py', 'simLIBS/stark_vamdc.py',
               'simLIBS/stark_resolver.py', 'tests/test_stark_data_collect.py',
               'tests/test_stark_vamdc.py', 'tests/test_stark_html_collect.py', '.gitignore']
    result['source_sha256'] = {s: hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources}
    destination = Path(__file__).with_name('stark_review_evidence.json')
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2)+chr(10), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
