"""Frozen Git export must create identical distribution bytes; real index unchanged."""
import io,os,subprocess,tarfile,tempfile,unittest
from pathlib import Path
from heideng_merchant.distribution import source_files,build_bundle
ROOT=Path(__file__).resolve().parents[1]
class MatureEolTests(unittest.TestCase):
    def test_working_snapshot_matches_canonical_git_export(self):
        with tempfile.TemporaryDirectory(prefix='merchant-eol-') as d:
            base=Path(d);env=dict(os.environ,GIT_INDEX_FILE=str(base/'index'))
            subprocess.run(['git','-C',str(ROOT),'read-tree','HEAD'],env=env,check=True,capture_output=True)
            selected=[*source_files(ROOT),'.gitattributes']
            paths=base/'paths';paths.write_text('\n'.join(selected)+'\n',encoding='utf-8',newline='\n')
            subprocess.run(['git','-C',str(ROOT),'add','--pathspec-from-file='+str(paths)],env=env,check=True,capture_output=True)
            tree=subprocess.check_output(['git','-C',str(ROOT),'write-tree'],env=env,text=True).strip()
            raw=subprocess.check_output(['git','-C',str(ROOT),'archive',tree],env=env)
            export=base/'export';export.mkdir()
            with tarfile.open(fileobj=io.BytesIO(raw)) as tf:tf.extractall(export,filter='data')
            self.assertEqual(source_files(ROOT),source_files(export))
            version=(ROOT/'VERSION').read_text().strip()
            work=build_bundle(ROOT,base/'work.zip',version);snapshot=build_bundle(export,base/'git.zip',version)
            self.assertEqual(work.read_bytes(),snapshot.read_bytes())
if __name__=='__main__':unittest.main()
