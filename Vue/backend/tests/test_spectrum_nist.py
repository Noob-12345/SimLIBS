import hashlib
import io
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
import requests
import time

from simlibs_ui.spectrum_nist import element_urls, parse_html, _safe_url, _get, PERIODIC_URL

ROOT = Path(__file__).parents[2]
FIX = ROOT / '.herdrflow/tasks/T004/fixtures'


class NistTests(unittest.TestCase):
    def test_real_captured_fe_double_row_and_source_fields(self):
        html = (FIX / 'iron3.html').read_bytes(); url = 'https://physics.nist.gov/PhysRefData/Handbook/Tables/irontable3.htm'
        group = parse_html(html, url, 'Fe', 'I')
        self.assertGreater(group['count'], 0)
        self.assertEqual(group['source'], url)
        self.assertEqual(group['sha256'], hashlib.sha256(html).hexdigest())
        state = group['positions'][0]['records'][0]['states'][0]
        self.assertEqual(state['wavelength_angstrom'], '2483.2708')
        self.assertEqual(state['energy_unit'], 'cm^-1')
        self.assertEqual(state['aki_unit'], '10^8 s^-1')
        self.assertTrue(state['configuration']); self.assertTrue(state['term']); self.assertTrue(state['j'])
        self.assertGreaterEqual(len(group['positions'][0]['records']), 2)

    def test_empty_values_and_missing_state_are_not_fabricated(self):
        html=(FIX/'iron3.html').read_bytes(); group=parse_html(html,'https://physics.nist.gov/PhysRefData/Handbook/Tables/irontable3.htm','Fe','I')
        state=group['positions'][0]['records'][1]['states'][0]
        self.assertEqual(state['wavelength_angstrom'],''); self.assertEqual(state['aki'],''); self.assertEqual(state['line_ref'],'')
        with self.assertRaises(ValueError): parse_html(b'<html><title>Error</title><body>404</body></html>','https://physics.nist.gov/PhysRefData/Handbook/Tables/irontable3.htm','Fe','I')
        with self.assertRaises(ValueError): parse_html(html,'https://physics.nist.gov/PhysRefData/Handbook/Tables/irontable3.htm','Fe','III')

    def test_url_allowlist_and_periodic_link(self):
        for url in ('http://physics.nist.gov/PhysRefData/Handbook/Tables/irontable3.htm','https://example.com/PhysRefData/Handbook/Tables/irontable3.htm','https://physics.nist.gov/private'):
            with self.assertRaises(ValueError): _safe_url(url)
        session=Mock();response=MagicMock(content=b'<html><title>NIST: Basic Atomic Spectroscopic Data - Perodic Table</title><a href="Tables/irontable1.htm">Fe</a></html>',status_code=200,url=PERIODIC_URL,headers={'Content-Type':'text/html'})
        response.iter_content.return_value=[response.content];session.get.return_value=response;response.__enter__.return_value=response
        self.assertEqual(element_urls('Fe',session)['I'].endswith('irontable3.htm'),True)
        self.assertTrue(session.get.call_args.kwargs['verify']);self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
        with self.assertRaises(ValueError): element_urls('../Fe',session)

    def test_missing_species_is_reported(self):
        html=(FIX/'iron3.html').read_bytes()
        with patch('simlibs_ui.spectrum_nist._get', side_effect=[(FIX/'periodic.html').read_bytes(), html, ValueError('timeout')]):
            from simlibs_ui.spectrum_nist import fetch
            result=fetch('Fe')
        self.assertIn('I',result['available_states']); self.assertEqual(result['available_states']['II'],'missing'); self.assertTrue(result['issues'])

    def test_timeout_size_redirect_content_and_deadline(self):
        session=Mock()
        session.get.side_effect=requests.Timeout('read timeout')
        with self.assertRaisesRegex(ValueError,'超时'): _get(session,PERIODIC_URL,time.monotonic()+10)
        session.get.side_effect=None
        response=MagicMock(status_code=200,url=PERIODIC_URL,headers={'Content-Type':'text/html'})
        response.__enter__.return_value=response;session.get.return_value=response
        for status in (404,500,302):
            response.status_code=status
            with self.assertRaisesRegex(ValueError,'HTTP'): _get(session,PERIODIC_URL,time.monotonic()+10)
        response.status_code=200;response.headers={'Content-Type':'application/json'}
        with self.assertRaises(ValueError):_get(session,PERIODIC_URL,time.monotonic()+10)
        response.headers={'Content-Type':'text/html','Content-Length':'16000001'}
        with self.assertRaisesRegex(ValueError,'16MB'):_get(session,PERIODIC_URL,time.monotonic()+10)
        response.headers={'Content-Type':'text/html'};response.iter_content.return_value=[b'x'*32]
        with patch('simlibs_ui.spectrum_nist.MAX_HTML',16):
            with self.assertRaisesRegex(ValueError,'16MB'):_get(session,PERIODIC_URL,time.monotonic()+10)
        with self.assertRaisesRegex(ValueError,'整体超时'):_get(session,PERIODIC_URL,time.monotonic()-1)
        for symbol in ('https://evil.test','Fe/../../../','fe','','Xx'):
            with self.assertRaises(ValueError):element_urls(symbol,session)

    def test_identity_spacer_and_partial_empty_rows(self):
        url='https://physics.nist.gov/PhysRefData/Handbook/Tables/irontable3.htm'
        html=(FIX/'iron3.html').read_bytes()
        for element,species in [('F','I'),('Fe','II'),('Mg','I')]:
            with self.assertRaises(ValueError):parse_html(html,url,element,species)
        empty=(FIX/'hydrogen4.html').read_bytes()
        with self.assertRaises(ValueError):parse_html(empty,'https://physics.nist.gov/PhysRefData/Handbook/Tables/hydrogentable4.htm','H','II')
        group=parse_html(html.replace(b'4.81',b'&nbsp;',1),url,'Fe','I')
        self.assertEqual(group['positions'][0]['records'][0]['states'][0]['aki'],'')
        self.assertEqual(group['positions'][0]['records'][0]['states'][0]['line'],4)
        self.assertEqual(len(group['positions'][0]['records']),2)

    def test_spacer_breaks_state_row_association(self):
        from bs4 import BeautifulSoup
        html = (FIX / 'iron3.html').read_bytes()
        url = 'https://physics.nist.gov/PhysRefData/Handbook/Tables/irontable3.htm'
        normal = parse_html(html, url, 'Fe', 'I')
        self.assertEqual(len(normal['positions'][0]['records']), 2)
        for spacer in ('<tr><td colspan="36"> </td></tr>', '<tr>'+'<td></td>'*9+'</tr>', '<tr><td>invalid</td></tr>'):
            soup = BeautifulSoup(html, 'html.parser')
            state_row = next(row for row in soup.find_all('tr') if row.find_parent('table') is soup.find_all('table')[-1] and '40257.311' in row.get_text())
            state_row.insert_before(BeautifulSoup(spacer, 'html.parser').tr)
            group = parse_html(str(soup).encode(), url, 'Fe', 'I')
            self.assertEqual(len(group['positions'][0]['records']), 1)
            self.assertFalse(any(s['energy']=='40257.311' for r in group['positions'][0]['records'] for s in r['states']))
            self.assertEqual(group['count'], normal['count'])


if __name__ == '__main__': unittest.main()
