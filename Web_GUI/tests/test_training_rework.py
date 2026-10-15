import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

import pandas as pd
from simlibs_ui.models import Parameters
from simlibs_ui.settings import UI_ROOT
from simlibs_ui.storage import read_history, save_result
from simlibs_ui.training import build_training_package


class IonAbundanceTests(unittest.TestCase):
    def test_invalid_abundance_rejected_with_without_total_and_blank_nonblank_cells(self):
        with tempfile.TemporaryDirectory() as temporary:
            for suffix in ('NaN','Inf','not-an-abundance','-0.1','1e309','','4.4e-2 units'):
                for total in (False,True):
                    for blank in (False,True):
                        with self.subTest(suffix=suffix,total=total,blank=blank):
                            path=Path(temporary)/'input.csv'
                            with path.open('w',newline='',encoding='utf-8') as stream:
                                writer=csv.writer(stream)
                                writer.writerow(['Wavelength (nm)',f'Fe I ({suffix})']+(['Sum(calc)'] if total else []))
                                writer.writerow([650,'' if blank else 0]+([0] if total else []))
                                writer.writerow([655,2]+([2] if total else []))
                            with self.assertRaises(ValueError):read_history(path)

    def test_plain_and_valid_finite_nonnegative_abundance_preserve_contributions(self):
        with tempfile.TemporaryDirectory() as temporary:
            for column in ('Fe I','Fe I (4.4e-2)','Fe I (0)','Fe I (.044)','Fe I (4.4E-2)','Fe I (+0.044)'):
                for total in (False,True):
                    with self.subTest(column=column,total=total):
                        path=Path(temporary)/'input.csv'
                        with path.open('w',newline='',encoding='utf-8') as stream:
                            writer=csv.writer(stream)
                            writer.writerow(['Wavelength (nm)',column]+(['Sum(calc)'] if total else []))
                            writer.writerow([650,'']+([0] if total else []));writer.writerow([655,2]+([2] if total else []))
                        frames,origin=read_history(path)
                        self.assertEqual(frames['raw']['intensity'].tolist(),[0,2])
                        self.assertEqual(frames['ion'][column].tolist(),[0,2])
                        self.assertEqual('ion_total' in origin,not total)


@unittest.skipUnless(os.name=='nt','Windows 跨身份权限回归')
class TrainingPublicationTests(unittest.TestCase):
    def setUp(self):
        # 普通 UI 输出目录，不能以私有 TemporaryDirectory 充当发布目录。
        self.path=UI_ROOT/'output'/('training-permission-test-'+uuid.uuid4().hex)
        self.path.mkdir()
        self.addCleanup(self.cleanup)
        p=Parameters()
        frame=pd.DataFrame({'wavelength':[650.,655.,660.],'intensity':[0.,2.,0.]})
        sample=save_result(self.path/'sample',{'interpolated':frame},{'kind':'simulation','parameters':p.to_dict()})
        self.manifest={'spec':{'batch_size':2},'samples':[sample],'requested':1,'partial':False,
                       'parameters':p.to_dict(),'origin':{'label':'offline permission fixture'}}

    def cleanup(self):
        assert self.path.resolve().is_relative_to((UI_ROOT/'output').resolve())
        shutil.rmtree(self.path)

    def test_independent_restricted_identity_reads_all_published_files_but_not_private_control(self):
        with tempfile.TemporaryDirectory(dir=self.path) as temporary:
            private=Path(temporary)/'private-control.txt';private.write_text('private')
            ordinary=self.path/'ordinary-control.txt';ordinary.write_text('normal inheritance')
            package=build_training_package(self.path,self.manifest)
            files=sorted((self.path/'training').iterdir())
            spec=self.path/'reader.json'
            spec.write_text(json.dumps({'files':[str(ordinary),str(private)]+[str(p) for p in files]}),encoding='utf-8')
            process=subprocess.run([sys.executable,'-B',str(UI_ROOT/'tests'/'windows_read_context.py'),str(spec)],
                                   capture_output=True,text=True,encoding='utf-8',check=True)
            report=json.loads(process.stdout)
            self.assertTrue(report['files'][0]['readable'],'正常继承控制文件应可读')
            self.assertFalse(report['files'][1]['readable'],'受限身份必须拒绝私有控制文件，避免同身份假通过')
            self.assertEqual(len(files),5)
            self.assertTrue(all(row['readable'] for row in report['files'][2:]),report)

    def test_existing_target_remains_unchanged(self):
        target=self.path/'training';target.mkdir()
        marker=target/'keep.txt';marker.write_text('existing output')
        with self.assertRaises(FileExistsError):build_training_package(self.path,self.manifest)
        self.assertEqual(marker.read_text(),'existing output')
        self.assertEqual(list(target.iterdir()),[marker])

    def test_cancel_during_publication_leaves_no_published_target(self):
        def cancelled():
            return any(any(path.iterdir()) for path in self.path.glob('.training-publish-*'))
        with self.assertRaises(InterruptedError):build_training_package(self.path,self.manifest,cancelled)
        self.assertFalse((self.path/'training').exists())
        self.assertFalse(list(self.path.glob('.training-publish-*')))


if __name__=='__main__':unittest.main()
