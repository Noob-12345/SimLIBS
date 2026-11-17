"""Public instrument samples cross-checked against fixed upstream readers.
No user's instrument sample or universal device-version claim.
"""
import ctypes
import importlib.util
import io
import os
from pathlib import Path
import struct
import sys
import types
import unittest

import numpy as np
from simlibs_ui.spectrum_sif import decode as sif
from simlibs_ui.spectrum_avantes import decode as ava

REF = Path(os.environ.get('SIMLIBS_FORMAT_REFERENCES', Path(__file__).parents[2]/'.ai-workflow/20261117-spectrum-browser/references'))


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


class Instruments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all((REF/name).is_file() for name in ('raman1.sif','measurement.sif','cli-0.sif','public.Raw8','public.ROH','public.TRM','ava-reader.py','ava-types.py','sif-sif_parser__sif_open.py')):
            raise unittest.SkipTest('Public reference files absent; set SIMLIBS_FORMAT_REFERENCES to fixed-commit reference directory (see task fixtures-provenance.json/README). No network download in tests.')
    def test_public_sif_against_bsd_reader_all_frames_and_calibration(self):
        reference = module('reference_sif', REF/'sif-sif_parser__sif_open.py')
        for name in ('raman1.sif','cli-0.sif','measurement.sif'):
            data = (REF/name).read_bytes()
            tile,size,count,info = reference._open(io.BytesIO(data))
            result = sif(data)
            self.assertEqual(len(result['frames']), count*size[1])
            expected = np.frombuffer(data,dtype='<f4',offset=tile[0][2],count=count*size[0]*size[1]).reshape(count,size[1],size[0])
            for i,frame in enumerate(result['frames']):
                np.testing.assert_array_equal(frame['curves']['counts'],expected.reshape(-1,size[0])[i])
                np.testing.assert_allclose(frame['x'],np.polynomial.polynomial.polyval(np.arange(1,size[0]+1),info['Calibration_data']))
                self.assertEqual(frame['unit'],'nm')
            pixels=sif(data.replace(b'Wavelength',b'RamanShift',1))
            self.assertEqual(pixels['frames'][0]['unit'],'pixel')
            with self.assertRaises(ValueError):sif(data[:tile[0][2]+10])

    def test_public_raw8_against_mit_reader_and_explicit_little_endian(self):
        package=types.ModuleType('avaread');package.__path__=[]
        previous={key:sys.modules.get(key) for key in ('avaread','avaread.AvaTypes')}
        try:
            sys.modules['avaread']=package
            schema=module('avaread.AvaTypes',REF/'ava-types.py');sys.modules['avaread.AvaTypes']=schema
            reader=module('reference_ava',REF/'ava-reader.py')
            self.assertEqual(ctypes.sizeof(schema.AVSInfoBlock),322)
            self.assertEqual(ctypes.sizeof(schema.AVSPreamble),6)
            self.assertEqual(schema.AVSPreamble.channels.offset,5)
            reference=reader.AVSFile(REF/'public.Raw8')
            actual=ava((REF/'public.Raw8').read_bytes())
            np.testing.assert_array_equal(actual['frames'][0]['x'],reference[0].data[:,0])
            for i,key in enumerate(('scope','dark','reference'),1):
                np.testing.assert_array_equal(actual['frames'][0]['curves'][key],reference[0].data[:,i])
        finally:
            for key,old in previous.items():
                if old is None:sys.modules.pop(key,None)
                else:sys.modules[key]=old

    def test_sif_explicit_per_frame_calibration_and_variable_roi_bins(self):
        reference = module('reference_sif_cal', REF/'sif-sif_parser__sif_open.py')
        data = (REF/'measurement.sif').read_bytes()
        calls = []; original = reference._read_string
        def observe(fp, length=None):
            start=fp.tell(); value=original(fp,length)
            if length is None:calls.append((start,fp.tell(),value))
            return value
        reference._read_string=observe;reference._open(io.BytesIO(data))
        start,end,_=calls[1]
        # Constructed header variants, not additional instrument sample claims.
        for newline in (False,True):
            user=bytes([10]).join((f'Calibration data for frame {i+1}'+ (chr(10) if newline else ': ')+f'{400+i}, 0.1, 0, 0').encode() for i in range(20))
            variant=data[:start]+str(len(user)).encode()+bytes([10])+user+data[end:]
            parsed=sif(variant)
            for i,f in enumerate(parsed['frames']):
                np.testing.assert_allclose(f['x'],400+i+.1*np.arange(1,1025))
        seed=(REF/'cli-0.sif').read_bytes();prefix=seed[:seed.index(b'65541 ')]
        header=bytes([10]).join([b'65541 1 4 20 1 1 2 10 10',b'65538 10 1 17 1 1 2',b'65538 20 4 25 1 2 2',b'0',b'0',b''])
        variant=prefix+header+np.arange(10,dtype='<f4').tobytes()
        parsed=sif(variant);self.assertEqual(len(parsed['frames']),3)
        self.assertEqual([len(f['x']) for f in parsed['frames']],[4,3,3])
        coefs=parsed['frames'][0]['metadata']['calibration']
        np.testing.assert_allclose(parsed['frames'][0]['x'],np.polynomial.polynomial.polyval([10.5,12.5,14.5,16.5],coefs))
        np.testing.assert_array_equal(parsed['frames'][2]['curves']['counts'],[7,8,9])

    def test_raw82_multichannel_negative_scope_truncation_unknown(self):
        data=(REF/'public.Raw8').read_bytes();block=data[6:]
        both=b'AVS82'+bytes([2])+block+block
        result=ava(both);self.assertEqual(len(result['frames']),2)
        np.testing.assert_array_equal(result['frames'][0]['curves']['dark'],result['frames'][1]['curves']['dark'])
        negative=bytearray(data);struct.pack_into('<f',negative,6+322+1019*4,-23.5)
        self.assertEqual(ava(negative)['frames'][0]['curves']['scope'][0],-23.5)
        for bad in (data[:-100],b'AVS99'+data[5:],b'unknown raw'):
            with self.assertRaises(ValueError):ava(bad)

    def test_public_legacy70_exact_layout_without_processed_substitution(self):
        for name,parts in [('public.ROH',1),('public.TRM',3)]:
            data=(REF/name).read_bytes();actual=ava(data)['frames'][0]
            first,last=struct.unpack_from('<2f',data,316);count=int(last-first+1)
            expected=np.frombuffer(data,dtype='<f4',offset=400,count=count*parts).reshape(count,parts)
            np.testing.assert_array_equal(actual['curves']['scope'],expected[:,0])
            if parts==3:
                np.testing.assert_array_equal(actual['curves']['reference'],expected[:,1])
                np.testing.assert_array_equal(actual['curves']['dark'],expected[:,2])
            coef=struct.unpack_from('<5f',data,296)
            np.testing.assert_allclose(actual['x'],np.polynomial.polynomial.polyval(np.arange(first,last+1),coef))


if __name__=='__main__':unittest.main()
