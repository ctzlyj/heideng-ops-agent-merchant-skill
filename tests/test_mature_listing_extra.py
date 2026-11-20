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
        with self.assertRaisesRegex(RuntimeError,'--analysis-file.*no model request submitted'):
            module.read_analysis(None)

    def test_replica_inventory_and_reuse_source_carousel_through_generation_cli(self):
        import json
        from unittest.mock import patch
        from PIL import Image
        preflight = load("hot_replica_preflight")
        generator = load("company_jpeg_edits")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft = root / "42_demo"
            draft.mkdir()
            def write(path, data):
                path.write_text(json.dumps(data), encoding="utf-8")
            for n in (1, 2):
                Image.new("RGB", (63, 53), (n * 60, 0, 30)).save(draft / f"main{n}.png")
            write(root / "category.json", {"brands": [{"brandId": -1}]})
            write(root / "analysis.json", {"drops": [], "continuity": {"pages": []}})
            write(draft / "listing.json", {"product": {"title": "product"}, "skus": [], "images": [
                {"role": "spu_main", "order": n, "localPath": f"main{n}.png", "imageKey": f"SPU-MAIN-{n:02d}"}
                for n in (2, 1)]})
            args = ["preflight", "--draft-root", str(root), "--sku", "42", "--reference", str(root / "category.json"),
                    "--analysis-file", str(root / "analysis.json")]
            with patch.object(sys, "argv", args), self.assertRaisesRegex(ValueError, "完整提示词"):
                preflight.main()
            work = draft / "hot-replica"
            inputs = json.loads((work / "design-input-42.json").read_text(encoding="utf-8"))
            self.assertEqual([row["source"] for row in inputs], ["main1.png", "main2.png"])
            write(root / "design.json", {row["imageKey"]: {"reuse": True} for row in inputs})
            with patch.object(sys, "argv", args + ["--image-prompts-file", str(root / "design.json")]):
                self.assertEqual(preflight.main(), 0)
            write(root / "store.json", {"store": {"profile": "test", "venderId": 12, "shopName": "sample"}})
            args = ["company_jpeg_edits", "--draft", str(draft), "--output", str(work),
                    "--plan", str(work / "remake-plan-42.json"), "--store-config", str(root / "store.json")]
            with patch.object(sys, "argv", args), patch.object(generator, "resolve_api_key", side_effect=AssertionError):
                generator.main()
            quote = json.loads((work / "image-quote.json").read_text(encoding="utf-8"))
            self.assertEqual((quote["newImageCount"], len(quote["reusedSources"])), (0, 2))
            plan = json.loads((work / "remake-plan-42.json").read_text(encoding="utf-8"))
            for row in plan["images"]:
                with Image.open(draft / row["output"]) as output, Image.open(draft / row["source"]) as original:
                    self.assertEqual(output.tobytes(), original.tobytes())

    def test_all_new_entries_help_without_model_or_store(self):
        for name in ['taobao_product_mvp','hot_replica_apply','hot_replica_price_plan','hot_replica_preflight']:
            result=subprocess.run([sys.executable,'-I',str(ROOT/'scripts/mature_entry.py'),str(SCRIPTS/(name+'.py')),'--help'],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace')[-800:])

if __name__=='__main__':unittest.main()
