"""Only new source-boundary adaptations; no real source fetch, auth, model or writes."""
import importlib.util,sys,tempfile,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'mature/listing/scripts'

def load(name):
    sys.path.insert(0,str(SCRIPTS))
    spec=importlib.util.spec_from_file_location('_extra_'+name,SCRIPTS/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class ExtraListingTests(unittest.TestCase):
    def test_real_taobao_and_tmall_id_parser_is_retained(self):
        module=load('taobao_product_mvp')
        self.assertEqual(module.taobao_item_id('https://item.taobao.com/item.htm?id=12345'),'12345')
        self.assertEqual(module.taobao_item_id('https://detail.tmall.com/item.htm?id=67890'),'67890')

    def test_unconfigured_vision_refuses_before_image_read_or_paid_call(self):
        module=load('hot_replica_preflight')
        with self.assertRaisesRegex(RuntimeError,'external-vision-provider-not-configured'):
            module.ask(Path('does-not-exist.png'),'synthetic product','unspecified')

    def test_all_new_entries_help_without_model_or_store(self):
        for name in ['taobao_product_mvp','hot_replica_apply','hot_replica_price_plan','hot_replica_preflight']:
            result=subprocess.run([sys.executable,'-I',str(ROOT/'scripts/mature_entry.py'),str(SCRIPTS/(name+'.py')),'--help'],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace')[-800:])

if __name__=='__main__':unittest.main()
