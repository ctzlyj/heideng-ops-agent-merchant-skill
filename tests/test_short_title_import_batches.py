"""Exercise the POP title workflow with real XLSX files and a local browser boundary."""
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from argparse import Namespace
from contextlib import closing, contextmanager, nullcontext, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openpyxl import Workbook, load_workbook
from tests import test_mature_materials as fixtures


MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
SHOP = {'shopName':'合成灯具店', 'shopId':'830', 'venderId':'260'}


def titles(count, start=0):
    # Descending, zero-prefixed text identifiers catch sorting and numeric conversion.
    return [(f'00{999999-index:08d}', f'家用灯具护眼款{index:05d}限定') for index in range(start,start+count)]


def read_rows(path):
    with closing(load_workbook(path,read_only=True,data_only=False)) as book:
        return list(book['Sheet1'].iter_rows(min_row=3,min_col=1,max_col=2,values_only=True))


def large_workbook(raw):
    """A valid official worksheet with a large stored XML comment and unchanged cell data."""
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(output,'w') as target:
        for item in source.infolist():
            content = source.read(item)
            if item.filename == 'xl/worksheets/sheet1.xml':
                content += b'<!--' + b'P' * MAX_BYTES + b'-->'
                item.compress_type = zipfile.ZIP_STORED
            target.writestr(item,content)
    return output.getvalue()


class LocalImportPage:
    """Only the upload widget, create response and displayed task rows are simulated."""

    def __init__(self, test, module):
        self.test = test
        self.uploads = []
        self.byte_counts = []
        self.creates = []
        self.tasks = {}
        self.details = {}
        self.reject = set()
        self.lose_create = None
        self.page = Mock(url=module.WARE_LIST_URL)
        self.drawer = Mock()
        self.page.on.side_effect = self.on_response
        self.page.expect_response.side_effect = self.expect_response
        self.drawer.locator.return_value.first.set_input_files.side_effect = self.upload
        context = Mock(pages=[self.page])
        for name,replacement in (
                ('_playwright',lambda:lambda:nullcontext(object())),
                ('_open',lambda *args:context),
                ('_observe_identity',lambda *args: {'id':True,'name':True}),
                ('_open_short_titles',self.open_drawer),
                ('_task_rows',self.task_rows)):
            test.enterContext(patch.object(module,name,replacement))

    def upload(self, file):
        # Playwright supports either a filesystem path or an in-memory FilePayload.
        # Inspect the exact bytes the widget was given.
        name = Path(file['name'] if isinstance(file,dict) else file).name
        content = file['buffer'] if isinstance(file,dict) else Path(file).read_bytes()
        rows = read_rows(io.BytesIO(content))
        self.test.assertGreater(len(rows),0)
        self.test.assertLessEqual(len(rows),MAX_ROWS,'oversized row count reached the upload widget')
        self.test.assertLessEqual(len(content),MAX_BYTES,'oversized XLSX reached the upload widget')
        self.uploads.append((name,rows))
        self.byte_counts.append(len(content))

    def on_response(self, event, callback):
        if event == 'response':
            self.callback = callback

    def refresh(self):
        self.callback(SimpleNamespace(url='https://fixture.invalid/batchJobService.queryByPage',
                      json=lambda:{'data':{'batchJobRecordDtoList':list(self.tasks.values())}}))

    def open_drawer(self, *args):
        self.refresh()
        return self.drawer

    def task_rows(self, drawer):
        return [f"任务 {task} 已完成 成功：{row['success']} 失败：{row['failed']}" for task,row in self.tasks.items()]

    @contextmanager
    def expect_response(self, predicate, timeout):
        event = SimpleNamespace()
        yield event
        upload_url = 'https://fixture.invalid/file.upload'
        if predicate(SimpleNamespace(url=upload_url)):
            source = 'https://fixture.invalid/upload/' + str(len(self.uploads))
            value = {'code':200,'data':{'url':source}}
        else:
            self.test.assertTrue(predicate(SimpleNamespace(url='https://fixture.invalid/batchJobService.createImportJob')))
            path,rows = self.uploads[-1]
            self.creates.append(path)
            if len(self.creates) == self.lose_create:
                raise TimeoutError('synthetic create response lost')
            task = str(820000 + len(self.creates))
            failures = [sku for sku,title in rows if sku in self.reject and title.endswith('限定')]
            record = {'jobExecId':task,'success':len(rows)-len(failures),'failed':len(failures)}
            if failures:
                url = 'https://fixture.invalid/result/' + task
                book = Workbook(write_only=True)
                sheet = book.create_sheet('逐行回执')
                sheet.append(['SKUID','执行结果','失败原因'])
                failed = set(failures)
                for sku,_ in reversed(rows):
                    sheet.append([sku,'失败','包含敏感词【["限定"]】'] if sku in failed else [sku,'成功',''])
                stream = io.BytesIO()
                book.save(stream)
                book.close()
                self.details[url] = stream.getvalue()
                record['jobExecFileRst'] = url
            self.tasks[task] = record
            self.refresh()
            value = {'code':200,'data':{'jobExecId':task}}
        event.value = SimpleNamespace(json=lambda:value)


class ShortTitleBatchTests(unittest.TestCase):
    def setUp(self):
        fixtures.MatureMaterialsTests.setUp(self)
        self.addCleanup(fixtures.MatureMaterialsTests.tearDown,self)
        self.agent = fixtures.MatureMaterialsTests.agent(self)
        import pop_browser, pop_workflow
        self.browser, self.workflow = pop_browser,pop_workflow
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':str(self.root/'state')}))
        self.profile = self.root/'state'/'browser-profiles'/'fixture'
        self.profile.mkdir(parents=True)
        self.args = Namespace(profile='fixture',profile_dir=str(self.profile),output_dir=self.root/'task',title_poll_seconds=0)
        self.page = LocalImportPage(self,self.browser)
        self.enterContext(patch('httpx.get', side_effect=lambda url,**kwargs:Mock(content=self.page.details[url])))
        self.enterContext(patch.object(self.agent,'audit_pop_coverage',return_value={'rows':[]}))

    def workbook(self, name, rows, *, large=False):
        raw = self.agent._short_title_workbook_bytes(rows)
        path = self.root/name
        path.write_bytes(large_workbook(raw) if large else raw)
        return path

    def maintain(self, files, count):
        delivery = {'shortTitleFiles':[str(path) for path in files],'plannedRowCount':count,'rowCount':count}
        return self.workflow.complete_short_title_import(self.args,delivery,SHOP,object(),self.agent)

    def test_registered_cli_imports_real_oversized_archive_without_touching_source(self):
        rows = titles(4)
        path = self.workbook('真实超限表.xlsx',rows,large=True)
        original = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertGreater(path.stat().st_size,MAX_BYTES)
        self.assertEqual(read_rows(path),rows)
        args = ['import-short-titles','--profile-dir',str(self.profile),'--workbook',str(path),
                '--expected-shop-name',SHOP['shopName'],'--expected-shop-id',SHOP['shopId']]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.browser.main(args),0)
        self.assertEqual([row for _,batch in self.page.uploads for row in batch],rows)
        self.assertTrue(all(name != path.name for name,_ in self.page.uploads))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),original)
        validation = self.agent.validate_short_title_workbook(path)
        self.assertTrue(validation['valid'])
        self.assertFalse(validation['validForSingleImport'])
        self.assertIn('byte-limit',validation['splitReasons'])

    def test_5000_original_and_5001_legacy_completed_chunk_are_reused(self):
        rows = titles(MAX_ROWS+1)
        ordinary = self.workbook('可直接导入.xlsx',rows[:MAX_ROWS])
        self.maintain([ordinary],MAX_ROWS)
        self.assertEqual(self.page.uploads,[(ordinary.name,rows[:MAX_ROWS])])
        source = self.workbook('大批次.xlsx',rows)
        raw = ordinary.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        legacy = self.args.output_dir/'.state'/'title-import-chunks'/(digest[:20]+'.xlsx')
        receipt = legacy.parent/'.state'/('title-import-'+digest[:16]+'.json')
        receipt.parent.mkdir(parents=True,exist_ok=True)
        legacy.write_bytes(raw)
        task = '719999'
        saved = {'status':'import-completed','taskId':task,'creationAccepted':True,'rowCount':MAX_ROWS,
                 'successRows':MAX_ROWS,'failedRows':0,'sha256':digest,'shopId':SHOP['shopId'],'shopName':SHOP['shopName']}
        receipt.write_text(json.dumps(saved),encoding='utf-8')
        self.page.tasks[task] = {'jobExecId':task,'success':MAX_ROWS,'failed':0}
        result = self.maintain([source],len(rows))
        self.assertEqual(len(self.page.creates),2,'the original completed chunk was submitted again')
        self.assertEqual(self.page.uploads[-1][1],rows[-1:])
        self.assertEqual([item['rowCount'] for item in result['imports']],[5000,1])
        self.assertEqual(result['imports'][0]['taskId'],task)
        self.assertEqual(read_rows(legacy),rows[:MAX_ROWS])

    def test_retry_of_unknown_import_never_replays_a_completed_or_uncertain_create(self):
        rows = titles(3)
        sources = [self.workbook(f'{i}.xlsx',[row]) for i,row in enumerate(rows)]
        self.page.lose_create = 2
        for _ in range(2):
            result = self.maintain(sources,len(rows))
            self.assertFalse(result['platformTitleImportVerified'])
            self.assertEqual([row for _,batch in self.page.uploads for row in batch],rows[:2])
            self.assertEqual(self.page.creates,[path.name for path in sources[:2]])

    def test_5001_confirmed_failures_from_two_tasks_repair_only_those_rows_in_source_order(self):
        rows = titles(5003)
        first = self.workbook('第一张表.xlsx',rows[:3001])
        second = self.workbook('第二张表.xlsx',rows[3001:])
        failed = rows[1:-1]
        self.page.reject = {sku for sku,_ in failed}
        result = self.maintain([first,second],len(rows))
        self.assertEqual([len(batch) for _,batch in self.page.uploads],[3001,2002,5000,1])
        self.assertEqual([part['byteCount'] for part in result['rowRepair']['imports']], self.page.byte_counts[2:])
        actual = [row for _,batch in self.page.uploads[2:] for row in batch]
        self.assertEqual(actual,[(sku,title.removesuffix('限定')) for sku,title in failed])
        self.assertEqual(len(self.page.creates),4)
        self.assertEqual(result.get('platformFailedRows',0),0)
        from heideng_merchant.merchant_experience import task_summary
        self.assertEqual(task_summary(result)['failedCount'],0)
        prior=task_summary({'status':'prior-batch-reconciliation'})
        self.assertEqual(prior['phase'],'needs-reconciliation')
        self.assertIn('原批次',prior['message'])

    def test_uncertain_repair_of_last_batch_does_not_replay_any_submission(self):
        import pop_title_batches as batches
        rows = titles(4)
        files = [self.workbook('first.xlsx',rows[:2]),self.workbook('second.xlsx',rows[2:])]
        self.page.reject = {sku for sku,_ in rows[:3]}
        self.page.lose_create = 4
        with patch.object(batches,'IMPORT_MAX_ROWS',2):
            for _ in range(2):
                result = self.maintain(files,len(rows))
                self.assertFalse(result['platformTitleImportVerified'])
                self.assertEqual(len(self.page.creates),4)
                self.assertEqual([len(batch) for _,batch in self.page.uploads],[2,2,2,1])
                repair = result['rowRepair']
                self.assertEqual([part['status'] for part in repair['imports']],['import-completed','unknown'])
                self.assertEqual(result['initialImportCounts'],{'successRows':1,'failedRows':3})
                self.assertEqual((result['successRows'],result['platformFailedRows'],result['unconfirmedRepairRows']),(3,0,1))
                self.assertEqual(result['unresolvedRows'],1)
                from heideng_merchant.merchant_experience import task_summary
                self.assertEqual(task_summary(result)['phase'],'needs-reconciliation')
                self.assertEqual(task_summary(result)['failedCount'],0)

    def test_multiple_sources_preflight_limits_and_empty_delivery(self):
        rows = titles(3)
        first = self.workbook('含中文.xlsx',rows[:2],large=True)
        last = self.workbook('第二来源.xlsx',rows[2:])
        self.assertEqual(self.maintain([],0)['status'],'no-titles')
        self.assertEqual(self.page.creates,[])
        self.maintain([first,last],len(rows))
        self.assertEqual([row for _,batch in self.page.uploads for row in batch],rows)
        self.assertEqual(self.page.uploads[-1][0],last.name)

    def test_one_row_cannot_fit_and_invalid_second_source_writes_nothing(self):
        import pop_title_batches as batches
        path = self.workbook('one.xlsx',titles(1))
        with patch.object(batches,'IMPORT_MAX_BYTES',128):
            refused=self.maintain([path],1)
        self.assertEqual(refused['status'],'blocked-import')
        self.assertIn('128',refused['reason'])
        other = self.workbook('blank.xlsx',[])
        refused=self.maintain([path,other],1)
        self.assertEqual(refused['status'],'blocked-import')
        self.assertIn(other.name,refused['reason'])
        self.assertEqual(self.page.creates,[])

    def test_lost_first_file_upload_is_not_replayed(self):
        path=self.workbook('single.xlsx',titles(1))
        original=self.page.upload
        def lost(file):
            original(file)
            raise TimeoutError('file upload started, response lost')
        self.page.drawer.locator.return_value.first.set_input_files.side_effect=lost
        for _ in range(2):
            result=self.maintain([path],1)
            self.assertEqual(result['status'],'unknown')
            self.assertEqual(len(self.page.uploads),1)
            self.assertFalse(self.page.creates)

    def test_preupload_browser_problem_can_resume_same_split_plan(self):
        import pop_title_batches as batches
        path=self.workbook('retry.xlsx',titles(3))
        with patch.object(batches,'IMPORT_MAX_ROWS',2):
            with patch.object(self.browser,'_open_short_titles',side_effect=ValueError('fixture browser unavailable')):
                first=self.maintain([path],3)
            self.assertEqual(first['status'],'blocked-import')
            self.assertEqual(first['imports'][0]['dispatchState'],'before-upload')
            self.assertFalse(self.page.uploads)
            second=self.maintain([path],3)
        self.assertEqual(second['successRows'],3)
        self.assertEqual(len(self.page.uploads),2)

    def test_rebuilt_files_still_over_the_limit_are_split_at_measured_serialized_size(self):
        import pop_title_batches as batches
        rows = titles(19)
        path = self.workbook('requires-smaller-batches.xlsx',rows)
        cap = len(self.agent._short_title_workbook_bytes(rows[:4]))
        self.assertLess(cap,path.stat().st_size)
        with patch.object(batches,'IMPORT_MAX_BYTES',cap):
            planned = batches.prepare_import_batches([path],self.args.output_dir,agent=self.agent)
            again = batches.prepare_import_batches([path],self.args.output_dir,agent=self.agent)
        self.assertEqual(planned,again)
        self.assertGreater(len(planned),1)
        actual = []
        for batch in planned:
            file = Path(batch['path'])
            payload = file.read_bytes()
            self.assertLessEqual(len(payload),cap)
            self.assertEqual((len(payload),hashlib.sha256(payload).hexdigest()),(batch['byteCount'],batch['sha256']))
            actual.extend(read_rows(file))
        self.assertEqual(actual,rows)

    def test_existing_oversize_source_receipt_is_reconciled_before_repartitioning(self):
        rows = titles(3)
        source = self.workbook('historical.xlsx',rows,large=True)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        original = source.parent/'.state'/('title-import-'+digest[:16]+'.json')
        original.parent.mkdir(parents=True)
        original.write_text(json.dumps({'status':'unknown','rowCount':len(rows),'sha256':digest,
                              'shopName':SHOP['shopName'],'shopId':SHOP['shopId']}),encoding='utf-8')
        result = self.browser.import_short_titles(str(self.profile),str(source),expected_shop_name=SHOP['shopName'],
                                                  expected_shop_id=SHOP['shopId'],poll_seconds=0)
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(self.page.uploads,[])
        self.assertEqual(self.page.creates,[])
        self.assertTrue(original.is_file())

    def test_independent_lane_finds_legacy_chunk_receipt_on_both_entrypoints(self):
        rows = titles(5001)
        lane = self.args.output_dir/'短标题独立交付'/'全店'
        self.args.output_dir = lane
        lane.mkdir(parents=True)
        source = lane/'短标题导入.xlsx'
        source.write_bytes(self.agent._short_title_workbook_bytes(rows))
        content = self.agent._short_title_workbook_bytes(rows[:5000])
        digest = hashlib.sha256(content).hexdigest()
        old_chunk = lane/'.state'/'title-import-chunks'/(digest[:20]+'.xlsx')
        receipt = old_chunk.parent/'.state'/('title-import-'+digest[:16]+'.json')
        receipt.parent.mkdir(parents=True)
        old_chunk.write_bytes(content)
        receipt.write_text(json.dumps({'status':'unknown','sha256':digest,'rowCount':5000,
                           'shopId':SHOP['shopId'],'shopName':SHOP['shopName']}),encoding='utf-8')
        result = self.maintain([source],len(rows))
        self.assertFalse(result['platformTitleImportVerified'])
        self.assertEqual(self.page.creates,[],'the 0.4.24 lane already has an unresolved first batch')
        self.browser.import_short_titles(str(self.profile),str(source),expected_shop_name=SHOP['shopName'],
                                        expected_shop_id=SHOP['shopId'],poll_seconds=0)
        self.assertEqual(self.page.uploads,[])
        self.assertTrue(receipt.is_file())

    def test_disjoint_receipts_across_lane_and_task_root_are_checked_per_chunk(self):
        import pop_title_batches as batches
        rows = titles(3)
        root = self.args.output_dir
        lane = root/'短标题独立交付'/'全店'
        lane.mkdir(parents=True)
        source = lane/'短标题导入.xlsx'
        source.write_bytes(self.agent._short_title_workbook_bytes(rows))
        originals = []
        for location,chunk,state in ((root,rows[:2],'import-completed'),(lane,rows[2:],'unknown')):
            content = self.agent._short_title_workbook_bytes(chunk)
            digest = hashlib.sha256(content).hexdigest()
            directory = location/'.state'/'title-import-chunks'
            (directory/'.state').mkdir(parents=True)
            file = directory/(digest[:20]+'.xlsx')
            file.write_bytes(content)
            receipt = directory/'.state'/('title-import-'+digest[:16]+'.json')
            saved = {'status':state,'sha256':digest,'shopId':SHOP['shopId'],'shopName':SHOP['shopName'],'rowCount':len(chunk)}
            if state == 'import-completed':
                saved.update(creationAccepted=True,taskId='779999',successRows=len(chunk),failedRows=0)
            receipt.write_text(json.dumps(saved),encoding='utf-8')
            originals.extend([file,receipt])
        with patch.object(batches,'IMPORT_MAX_ROWS',2):
            result = self.maintain([source],len(rows))
            self.assertEqual(result['status'],'unknown')
            self.assertEqual(self.page.uploads,[])
            self.assertEqual(self.page.creates,[])
            for original in originals:
                self.assertTrue(original.is_file())

    def test_existing_receipt_from_another_shop_never_uploads_or_creates(self):
        path = self.workbook('old.xlsx',titles(1))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt = path.parent/'.state'/('title-import-'+digest[:16]+'.json')
        receipt.parent.mkdir(exist_ok=True)
        receipt.write_text(json.dumps({'status':'import-completed','sha256':digest,
                           'shopId':'999','shopName':'另一家店','rowCount':1,'taskId':'700000'}),encoding='utf-8')
        result = self.maintain([path],1)
        self.assertFalse(result['platformTitleImportVerified'])
        self.assertEqual(self.page.uploads,[])
        self.assertEqual(self.page.creates,[])

    def test_source_default_receipt_can_be_an_explicit_batch_ledger_and_resume_on_both_entries(self):
        import pop_title_batches as batches
        rows = titles(3)
        source = self.workbook('source.xlsx',rows)
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        ledger = self.browser.batch_receipt_path(source,sha)
        options = {'expected_shop_name':SHOP['shopName'],'expected_shop_id':SHOP['shopId'],'poll_seconds':0}
        with patch.object(batches,'IMPORT_MAX_ROWS',2):
            first = self.browser.import_short_titles(str(self.profile),str(source),receipt_path=ledger,**options)
            self.assertEqual(first['status'],'import-completed')
            self.assertEqual(Path(first['receiptPath']),ledger)
            original = json.loads(ledger.read_bytes())
            original_tasks = [r['taskId'] for r in original['imports']]
            self.assertEqual([len(batch) for _,batch in self.page.uploads],[2,1])
            direct = self.browser.import_short_titles(str(self.profile),str(source),**options)
            maintained = self.maintain([source],len(rows))
            self.assertEqual([r['taskId'] for r in direct['imports']],original_tasks)
            self.assertEqual([r['taskId'] for r in maintained['imports']],original_tasks)
            self.assertEqual(len(self.page.uploads),2)
            self.assertEqual(len(self.page.creates),2)

    def test_missing_child_of_custom_ledger_stays_unknown_after_switching_entry_and_output(self):
        import pop_title_batches as batches
        rows = titles(3)
        source = self.workbook('source.xlsx',rows)
        ledger = self.root/'保存的原回执'/'任务.json'
        options = {'expected_shop_name':SHOP['shopName'],'expected_shop_id':SHOP['shopId'],'poll_seconds':0}
        with patch.object(batches,'IMPORT_MAX_ROWS',2):
            result = self.browser.import_short_titles(str(self.profile),str(source),receipt_path=ledger,**options)
            self.assertEqual(result['status'],'import-completed')
            receipt = Path(result['imports'][0]['receiptPath'])
            receipt.rename(receipt.with_suffix('.fixture-backup'))
            self.args.output_dir = self.root/'different-output'
            checked = self.maintain([source],len(rows))
            self.assertEqual(checked['status'],'unknown')
            self.assertEqual(len(self.page.creates),2)
            self.assertEqual(len(self.page.uploads),2)
            self.assertFalse(receipt.exists())

    def test_ledger_path_cannot_overwrite_source_child_workbook_receipt_or_lock(self):
        import pop_title_batches as batches
        source = self.workbook('source.xlsx',titles(3))
        with patch.object(batches,'IMPORT_MAX_ROWS',2):
            plan = batches.prepare_import_batches([source],source.parent,agent=self.agent)
            child = Path(plan[0]['path'])
            receipt = self.browser.batch_receipt_path(child,plan[0]['sha256'])
            lock = Path(str(receipt)+'.lock')
            protected = {p:p.read_bytes() if p.exists() else None for p in (source,child,receipt,lock)}
            for target in protected:
                with self.subTest(target=target.name), self.assertRaises(ValueError):
                    self.browser.import_short_titles(str(self.profile),str(source),receipt_path=target,
                        expected_shop_name=SHOP['shopName'],expected_shop_id=SHOP['shopId'])
            self.assertEqual({p:p.read_bytes() if p.exists() else None for p in protected},protected)
            self.assertEqual(self.page.uploads,[])
            self.assertEqual(self.page.creates,[])
