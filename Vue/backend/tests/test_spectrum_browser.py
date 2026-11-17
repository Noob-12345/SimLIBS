import base64
import hashlib
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import zipfile

from simlibs_ui.spectrum_browser import BrowserStore,parse,select,_xlsx
from simlibs_ui.spectrum_reference import markers,configured
from simlibs_ui.settings import Settings

REF=Path(__file__).parents[2]/'.ai-workflow/20261117-spectrum-browser/references'


def xlsx():
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="first" r:id="r1"/><sheet name="second" r:id="r2"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/></Relationships>')
        z.writestr('xl/sharedStrings.xml','<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>wavelength</t></si><si><t>signal</t></si></sst>')
        for i in (1,2):
            z.writestr(f'xl/worksheets/sheet{i}.xml',f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row><row r="2"><c r="A2"><v>400</v></c><c r="B2"><v>{-i}</v></c></row><row r="3"><c r="A3"><v>401</v></c><c r="B3"><v>{i*2}</v></c></row></sheetData></worksheet>')
    return output.getvalue()


class BrowserTests(unittest.TestCase):
    def test_reference_details_real_double_rows_units_and_unnamed(self):
        root=Path(Settings().line_database)
        fe=markers((root/'FeI.csv').read_bytes(),'FeI.csv',{'unit':'angstrom','fallback_column':1})[0]
        records=fe['positions'][0]['records'];self.assertEqual(len(records),2)
        self.assertEqual({s['role'] for r in records for s in r['states']},{'source row'})
        for state in [s for r in records for s in r['states']]:
            self.assertEqual(state['aki_unit'],'10^8 s^-1');self.assertEqual(state['energy_unit'],'cm^-1')
            self.assertTrue(state['configuration']);self.assertTrue(state['j']);self.assertTrue(state['g'])
        ce=markers((root/'CeII.csv').read_bytes(),'CeII.csv',{'unit':'angstrom','fallback_column':1})[0]
        for name,group in [('FeI.csv',fe),('CeII.csv',ce)]:
            self.assertEqual(group['source'],name)
            self.assertEqual(group['sha256'],hashlib.sha256((root/name).read_bytes()).hexdigest())
        self.assertEqual(ce['positions'][0]['records'][0]['states'][0]['energy_unit'],'cm^-1')
        repeated=b'Intensity,Wavelength (?),Aki,Energy,Configurations,Terms,J,g\n1,4000,,5,a,1S,0,1\n1,4000,,2,b,1P,1,3\n1,4000,,8,c,1D,2,5\n1,4000,,9,d,1F,3,7\n'
        group=markers(repeated,'FeII.csv')[0];self.assertEqual(group['count'],1)
        self.assertEqual(len(group['positions'][0]['records']),4)
        self.assertEqual(group['positions'][0]['records'][0]['states'][0]['role'],'source row')
        self.assertEqual(group['positions'][0]['records'][0]['states'][0]['aki'],'')
        simple=markers(b'lambda,element,species\n400,Fe,I\n401,Fe,I','user.csv',{'unit':'nm'})[0]
        state=simple['positions'][0]['records'][0]['states'][0]
        self.assertNotIn('energy',state);self.assertEqual(state['aki_unit'],'')
        for label,unit in [('aki (10^8 s^-1)','10^8 s^-1'),('aki (s^-1)','s^-1'),('aki','')]:
            data=('wavelength,'+label+',energy (eV),element,species'+chr(10)+'400,4.8,2.5,Fe,I').encode()
            row=markers(data,'user.csv',{'unit':'nm'})[0]['positions'][0]['records'][0]['states'][0]
            self.assertEqual(row['aki_unit'],unit);self.assertEqual(row['energy_unit'],'eV')
        with self.assertRaises(ValueError):configured(str(root/'does-not-exist'))
    def test_csv_units_columns_negatives_sort_duplicates_bad(self):
        doc=parse(b'\xef\xbb\xbf# measured\nwave;y1;y2\n500;-3;8\n400;2;-9\n','measured.csv')
        result=select(doc,{'x':0,'y':[1,2],'unit':'angstrom'})
        self.assertEqual(result['xs'],[40,50]);self.assertEqual(result['curves'][0]['ys'],[2,-3])
        self.assertEqual(result['curves'][1]['ys'],[-9,8]);self.assertTrue(result['provenance']['stable_sorted'])
        duplicate=parse(b'400,1\n400,-2\n401,3','a.csv')
        with self.assertRaisesRegex(ValueError,'重复'):select(duplicate,{})
        self.assertEqual(select(duplicate,{'duplicates':'keep'})['xs'],[400,400,401])
        for data in (b'400,1\n401,NaN',b'400,1\n401,Inf',b'400,1\n401,bad'):
            with self.assertRaises(ValueError):select(parse(data,'a.csv'),{})
        for options in ({'y':[0]},{'y':[4]},{'unit':'maybe'}):
            with self.assertRaises(ValueError):select(doc,options)
        with self.assertRaisesRegex(ValueError,'二进制'):parse(b'\0binary file contents','unknown.bin')

    def test_xlsx_sheets_shared_strings_limits_and_explicit_columns(self):
        doc=parse(xlsx(),'selected.xlsx');self.assertEqual(len(doc['tables']),2)
        result=select(doc,{'sheet':1,'x':0,'y':[1],'unit':'nm'})
        self.assertEqual(result['curves'][0]['ys'],[-2,4]);self.assertEqual(result['xs'],[400,401])
        with patch('simlibs_ui.spectrum_browser.MAX_CELLS',1):
            with self.assertRaisesRegex(ValueError,'单元格'):parse(xlsx(),'selected.xlsx')
        bad=io.BytesIO()
        with zipfile.ZipFile(bad,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('bomb','x'*1_000_000)
        with self.assertRaises(ValueError):_xlsx(bad.getvalue())

    def test_real_configured_species_and_missing_aki_are_positions(self):
        response=configured(Settings().line_database)
        self.assertFalse(response['issues'])
        keys={(g['element'],g['species']) for g in response['groups']}
        for key in [('Ce','II'),('Fe','I'),('Fe','II'),('Si','I'),('Si','II')]:self.assertIn(key,keys)
        no_aki=b'Intensity,Wavelength (?),Aki,Energy,Configurations,Terms,J,g\n1,4000,,0,,,,\n1,4000,,1,,,,\n2,4100,,0,,,,\n'
        group=markers(no_aki,'FeII.csv')[0]
        self.assertEqual((group['element'],group['species']),('Fe','II'));self.assertEqual(group['xs'],[400,410])
        for header in ('lambda','波长'):
            group=markers((header+',element,species\n400,Fe,II\n401,Fe,II').encode(),'user.csv',{'unit':'nm'})[0]
            self.assertEqual(group['xs'],[400,401])
        with self.assertRaises(ValueError):markers(b'lambda,element,species\n400,Fe,I','user.csv')

    def test_store_action_cycle_eviction_memory_limit_and_no_paths(self):
        store=BrowserStore();settings={'line_database':Settings().line_database}
        def upload(data,name):return store.call('import',dict(data=base64.b64encode(data).decode(),name=name),settings)
        a=upload(b'400,-2\n401,3','a.csv');b=upload(xlsx(),'b.xlsx')
        result=store.call('select',dict(document=b['document'],options={'sheet':1}),settings)
        self.assertEqual(result['curves'][0]['ys'],[-2,4])
        if REF.exists():
            c=upload((REF/'measurement.sif').read_bytes(),'test.sif')
            frame=store.call('select',dict(document=c['document'],options={'frame':'19:0:0'}),settings)
            self.assertEqual(frame['nodes'],1024)
            raw=upload((REF/'public.Raw8').read_bytes(),'instrument.raw')
            result=store.call('select',dict(document=raw['document'],options={'frame':'0','curves':['scope','dark']}),settings)
            self.assertEqual([x['id'] for x in result['curves']],['scope','dark'])
        self.assertLessEqual(len(store.documents),2)
        with self.assertRaises(ValueError):store.call('select',dict(document=a['document'],options={}),settings)
        with self.assertRaises(ValueError):store.call('import',dict(path='C:/private'),settings)
        with patch('simlibs_ui.spectrum_browser.MAX_CACHE',1):
            with self.assertRaisesRegex(ValueError,'内存'):upload(b'1,2\n2,3','a.csv')
        store.gate.acquire();store.gate.acquire()
        try:
            with self.assertRaises(ValueError):store.call('release',{},settings)
        finally:store.gate.release();store.gate.release()
        references=store.call('references',{},settings);self.assertTrue(references['groups'])
        references=store.call('references',dict(name='FeI.csv',data=base64.b64encode(b'400,1\n401,2').decode(),options={'unit':'nm'}),settings)
        self.assertEqual(references['groups'][0]['xs'],[400,401])


if __name__=='__main__':unittest.main()
