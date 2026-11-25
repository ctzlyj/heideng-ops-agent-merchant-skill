"""Exercise registered batch commands using real single-item guards and disposable official stores."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import unittest

from heideng_merchant.safety import atomic_json, read_json
from heideng_merchant.safety import file_sha
from tests.test_owned_product_copy import SOURCE,TARGET


class BatchCopyTests(unittest.TestCase):
    def setUp(self):
        from tests.test_shop_copy_entry import ShopCopyEntryTests
        ShopCopyEntryTests.setUp(self)
        self.sources={}
        self.destinations={}
        self.applies={}
        self.writes=[]
        self.reject={}
        self.lost=set()
        self.only_apply=set()
        self.bad_validation=set()
        self.validations=[]
        self.blueprints={}
        for i,pid in enumerate((701,702,703,704)):
            source,target=deepcopy(self.source),deepcopy(self.target)
            for product,identifier in ((source,pid),(target,pid+1000)):
                info=product['productInfo']
                info.update(productId=identifier,itemNum=f'COPY-{pid}',productName=f'样品 {pid}',productStatusNew=103)
                info['categoryDetail']['lastCategoryId']=800 if i<2 else 810+i
                for sku in product['skuList']:
                    sku['productId']=identifier
            self.sources[pid]=source
            self.blueprints[pid]=target
        api=self.entry.api
        original=api.get.side_effect
        def get(skill, url, params=None):
            shop=SOURCE if api.active_jdo_profile()==SOURCE['profile'] else TARGET
            records=self.sources if shop==SOURCE else self.destinations
            if url.endswith('/products/{productId}'):
                current=records[int(params['productId'])]
                if shop==SOURCE:self.source=current
                else:self.target=current
                return {'data':deepcopy(current)}
            if url.endswith('/product-apply/{applyId}'):
                return {'data':deepcopy(self.applies[int(params['applyId'])])}
            if url.endswith('/products'):
                rows=[{'productId':p,'productName':r['productInfo']['productName'],'productStatus':103,
                       'itemNum':r['productInfo']['itemNum']} for p,r in records.items()]
                if 'productIdList' in params:rows=[r for r in rows if r['productId'] in params['productIdList']]
                if 'itemNum' in params:rows=[r for r in rows if r['itemNum']==params['itemNum']]
                return {'success':True,'data':rows,'paginationData':{'currentPage':1,'pageNum':1,'totalItems':len(rows)}}
            return original(skill,url,params)
        api.get.side_effect=get
        def invoke(**kwargs):
            self.assertEqual(api.active_jdo_profile(),TARGET['profile'])
            payload=read_json(kwargs['body_path'])
            pid=int(next(c['value'] for c in json.loads(payload['schema']) if c['componentCode']=='WareItemnum').split('-')[-1])
            if kwargs['url'].endswith('/validations'):
                self.validations.append(pid)
                if pid in self.bad_validation:
                    return {'success':True,'data':{'wareKeeperDetectResultList':[{'detectResult':1}]}}
                return {'success':True,'data':{}}
            self.writes.append(pid)
            if pid in self.reject:
                return api.parse_response(json.dumps({'success':False,'errorList':[{'code':self.reject[pid]}]}),
                                          method='POST',url=kwargs['url'])
            target=deepcopy(self.blueprints[pid])
            self.destinations[pid+1000]=target
            self.applies[pid+9000]={**target,'applyInfo':{'applyId':pid+9000,'draftComputeStatus':1}}
            if pid in self.lost:raise TimeoutError('fixture: response lost after creation')
            data={'applyId':pid+9000}
            if pid not in self.only_apply:data['productId']=pid+1000
            return {'success':True,'data':data}
        api.run_jdo_large.side_effect=invoke

    def command(self,*args):
        out=StringIO()
        with redirect_stdout(out):
            self.entry.main(list(args))
        return json.loads(out.getvalue())

    def plan(self,ids=(701,702,703),*extra):
        inv=self.command('inventory',*self.src,*self.dst,'--status','103')
        args=[a for i in ids for a in ('--product-id',str(i))]
        result=self.command('batch-plan',*self.src,*self.dst,'--inventory',inv['inventoryFile'],*args,*extra)
        self.assertEqual(result['status'],'batch-planned',result)
        return result['batchId']

    def run_phase(self,batch,phase):
        confirm={'pilot':'PUBLISH_COPY_PILOT','bulk':'PUBLISH_FROZEN_SCOPE'}
        extra=['--confirm',confirm[phase],'--authorization-ref','合成原始交办'] if phase in confirm else []
        return self.command('batch-run',*self.src,*self.dst,'--batch',batch,'--phase',phase,
                            '--delivery-evidence',str(self.delivery),*extra)

    def resume(self,batch,*extra):
        return self.command('batch-resume',*self.src,*self.dst,'--batch',batch,*extra)

    def test_draft_pilot_grant_bulk_and_originals_after_restart(self):
        batch=self.plan()
        draft=self.run_phase(batch,'draft')
        self.assertEqual(draft['countsByStatus'],{'local-draft-ready':3})
        self.assertEqual(self.writes,[])
        self.upload.assert_not_called()
        pilot=self.run_phase(batch,'pilot')
        self.assertEqual(self.writes,[701],pilot)
        self.assertEqual(self.resume(batch)['phase'],'pilot')
        self.assertEqual(self.writes,[701])
        missing=self.command('batch-run',*self.src,*self.dst,'--batch',batch,'--phase','bulk')
        self.assertFalse(missing['ok'])
        bulk=self.run_phase(batch,'bulk')
        self.assertEqual(self.writes,[701,702,703],bulk)
        self.assertEqual((bulk['uniqueMappedTargets'],bulk['productsReadBack'],bulk['onSaleCount'],bulk['pendingAuditCount']),
                         (3,3,3,3))
        self.assertEqual(bulk['codeCoverage']['verified'],6)
        self.assertEqual(self.resume(batch)['comparedProductsMatch'],3)
        self.assertEqual(self.writes,[701,702,703])
        from heideng_merchant.merchant_tasks import task_context
        tasks=task_context(self.root,TARGET['shopId'],TARGET['venderId'],goal='shop-copy-batch')
        self.assertEqual(tasks['tasks'][0]['taskId'],batch)

    def test_unknown_create_is_polled_without_resubmitting_and_recovers_apply_only(self):
        self.lost.add(701)
        batch=self.plan((701,703))
        first=self.run_phase(batch,'bulk')
        self.assertEqual(first['status'],'batch-held',first)
        self.assertEqual(self.writes,[701])
        again=self.resume(batch)
        self.assertEqual(again['rows'][0]['candidateProductIds'],['1701'])
        self.assertEqual(self.writes,[701])
        task=again['rows'][0]['taskId']
        pub=self.entry.task_directory(task)/'publication'
        atomic_json(pub/'result.json',{'success':True,'data':{'applyId':9701}})
        self.assertEqual(self.resume(batch)['uniqueMappedTargets'],2)
        self.assertEqual(self.writes,[701,703])
        self.assertEqual(read_json(pub/'target-binding.json')['productId'],'1701')

    def test_original_apply_only_response_roundtrips_both_old_and_new_markers(self):
        self.only_apply.add(701)
        batch=self.plan((701,))
        result=self.run_phase(batch,'bulk')
        self.assertEqual(result['uniqueMappedTargets'],1,result)
        task=result['rows'][0]['taskId']
        pub=self.entry.task_directory(task)/'publication'
        marker=pub/'publish-body.submit-state.json'
        receipt=read_json(marker)
        self.assertEqual(receipt.pop('payloadSha256'),read_json(pub/'target-binding.json')['payloadSha256'])
        atomic_json(marker,receipt)
        (pub/'target-binding.json').unlink()
        self.assertEqual(self.resume(batch)['rows'][0]['targetProductId'],'1701')
        self.assertTrue(read_json(marker)['payloadSha256'])
        self.assertEqual(self.writes,[701])

    def test_business_refusal_holds_affected_category_but_not_independent_products(self):
        self.reject[701]='1010300506'
        batch=self.plan()
        result=self.run_phase(batch,'bulk')
        self.assertEqual([r['status'] for r in result['rows']],['publication-rejected','category-held','submitted'])
        self.assertEqual(self.writes,[701,703])
        self.resume(batch)
        self.assertEqual(self.writes,[701,703])
        self.assertEqual(self.validations,[701,703])

    def test_two_matching_permission_refusals_prevent_further_submissions(self):
        self.reject.update({701:'99904030008',703:'99904030008'})
        batch=self.plan((701,703,704))
        result=self.run_phase(batch,'bulk')
        self.assertEqual((result['status'],result['hold']['reason']),('batch-held','repeated-official-permission-refusal'))
        self.assertEqual(self.writes,[701,703])
        self.resume(batch)
        self.assertEqual(self.writes,[701,703])

    def test_same_failed_validation_is_not_posted_again_on_resume(self):
        self.bad_validation.add(701)
        batch=self.plan()
        self.run_phase(batch,'bulk')
        self.resume(batch)
        self.assertEqual(self.validations,[701,703])
        self.assertEqual(self.writes,[703])

    def test_explicit_stop_between_uploads_does_not_repeat_accepted_media(self):
        batch=self.plan((701,703))
        prior=self.upload.side_effect
        stopped=[]
        def before_return(zone,category,path):
            receipt=prior(zone,category,path)
            if not stopped:
                stopped.append(self.command('batch-stop','--batch',batch)['stopId'])
            return receipt
        self.upload.side_effect=before_return
        result=self.run_phase(batch,'bulk')
        self.assertEqual(result['status'],'batch-stopped')
        self.assertEqual((self.writes,self.upload.call_count),([],1))
        self.assertEqual(self.resume(batch)['status'],'batch-stopped')
        self.assertEqual(self.resume(batch,'--stop-id','outdated','--authorization-ref','继续')['status'],'batch-stopped')
        result=self.resume(batch,'--stop-id',stopped[0],'--authorization-ref','继续')
        self.assertEqual(self.writes,[701,703],result)
        self.assertEqual(result['uniqueMappedTargets'],2)

    def test_coverage_includes_all_frozen_source_skus_and_excludes_ambiguous_targets(self):
        from heideng_merchant.shop_copy_batch import directory
        sku=deepcopy(self.sources[702]['skuList'][0])
        sku.update(skuId=205,outerId='three')
        self.sources[702]['skuList'].append(sku)
        batch=self.plan()
        self.run_phase(batch,'draft')
        result=self.run_phase(batch,'pilot')
        coverage=result['codeCoverage']
        self.assertEqual((coverage['sourceSkuCount'],coverage['verified'],coverage['unverified']),(7,2,5))
        root=directory(batch)
        item=read_json(root/'items/702.json')
        atomic_json(root/'items/702.json',{**item,'status':'mapping-conflict','targetProductId':'1701'})
        result=self.command('batch-status','--batch',batch)
        self.assertEqual((result['uniqueMappedTargets'],result['codeCoverage']['verified'],result['codeCoverage']['unverified']),(0,0,7))
        fresh=self.plan((701,703))
        unseen=self.run_phase(fresh,'pilot')['codeCoverage']
        self.assertEqual(unseen['sourceProductsWithUnknownSkuCount'],0)  # The earlier batch froze both.
        another=self.plan((701,704))
        self.assertEqual(self.run_phase(another,'pilot')['codeCoverage']['sourceProductsWithUnknownSkuCount'],1)

    def test_product_id_only_existing_mapping_checks_original_application_without_writes(self):
        self.destinations[1701]=deepcopy(self.blueprints[701])
        self.applies[1701]={**self.destinations[1701],'applyInfo':{'applyId':9777,'draftComputeStatus':3}}
        mapping=self.root/'map.json'
        atomic_json(mapping,{'701':1701})
        batch=self.plan((701,703),'--existing-map',str(mapping))
        result=self.run_phase(batch,'bulk')
        self.assertEqual(result['hold']['reason'],'application-rejected')
        self.assertEqual((result['rejectedAuditCount'],result['onSaleCount']),(1,1))
        self.assertEqual(self.writes,[])
        self.upload.assert_not_called()

    def test_existing_on_sale_product_without_application_status_is_reported_as_unverified(self):
        self.destinations[1701]=deepcopy(self.blueprints[701])
        self.applies[1701]=deepcopy(self.destinations[1701])
        mapping=self.root/'existing-map.json'
        atomic_json(mapping,{'701':1701})
        batch=self.plan((701,),'--existing-map',str(mapping))
        row=self.run_phase(batch,'bulk')
        self.assertEqual((row['onSaleCount'],row['unverifiedSaleCount']),(1,0))
        self.assertEqual((row['pendingAuditCount'],row['rejectedAuditCount'],row['unverifiedAuditCount']),(0,0,1))

    def test_unrelated_category_errors_do_not_trigger_a_storewide_hold(self):
        self.reject.update({701:'1010300506',703:'99904030008'})
        batch=self.plan((701,703,704))
        result=self.run_phase(batch,'bulk')
        self.assertFalse(result['hold'].get('active'))
        self.assertEqual(self.writes,[701,703,704])

    def correction(self,result):
        row=result['rows'][0]
        root=self.entry.task_directory(row['taskId'])
        old=read_json(root/'publication/rejection.json')
        receipt=self.root/'现场运费规则.json'
        observed=read_json(self.delivery)
        observed['target']['freightTemplates'][0]['id']='191'
        atomic_json(receipt,observed)
        record={'taskId':row['taskId'],'targetShop':TARGET,'originalBodySha256':old['payloadSha256'],
                'platformCode':'1010300506','fields':['WareTransport'],'receipt':receipt.name,'receiptSha256':file_sha(receipt)}
        proof=self.root/'修正.json'
        atomic_json(proof,record)
        return root,receipt,proof

    def test_corrected_attempt_after_definite_refusal_is_scoped_durable_and_only_once(self):
        self.reject[701]='1010300506'
        batch=self.plan((701,702))
        refused=self.run_phase(batch,'bulk')
        self.assertEqual(self.writes,[701])
        root,receipt,proof=self.correction(refused)
        original=(root/'publication/publish-body.json').read_bytes()
        # A different host reference alone cannot repeat an unchanged request.
        del self.reject[701]
        self.resume(batch,'--correction-evidence',str(proof))
        self.assertEqual(self.writes,[701])
        self.blueprints[701]['productInfo']['logisticsInfo']['transportId']=191
        self.blueprints[702]['productInfo']['logisticsInfo']['transportId']=191
        fixed=self.resume(batch,'--correction-evidence',str(proof),'--delivery-evidence',str(receipt))
        self.assertEqual(self.writes,[701,701,702],fixed)
        self.assertEqual(fixed['uniqueMappedTargets'],2)
        self.assertEqual(original,(root/'publication/publish-body.json').read_bytes())
        from heideng_merchant.shop_copy_batch import publication_directory
        active=publication_directory(root)
        self.assertEqual(active,root/'publication/correction')
        self.assertEqual(read_json(active/'correction.json')['absence']['matchingProducts'],[])
        self.assertEqual(read_json(active/'result.json')['data']['productId'],1701)
        self.resume(batch,'--correction-evidence',str(proof))
        self.assertEqual(self.writes,[701,701,702])

    def test_refusal_cannot_retry_unknown_or_modified_evidence_and_existing_target_is_read_only(self):
        self.reject[701]='1010300506'
        batch=self.plan((701,))
        refused=self.run_phase(batch,'bulk')
        root,receipt,proof=self.correction(refused)
        saved=read_json(proof)
        atomic_json(proof,{**saved,'receiptSha256':'0'*64})
        self.resume(batch,'--correction-evidence',str(proof),'--delivery-evidence',str(receipt))
        self.assertEqual(self.writes,[701])
        atomic_json(proof,saved)
        self.destinations[1701]=deepcopy(self.blueprints[701])
        adopted=self.resume(batch,'--correction-evidence',str(proof))
        self.assertEqual(adopted['rows'][0]['status'],'existing-target-for-comparison',adopted)
        self.assertTrue((root/'publication/existing-after-rejection.json').is_file())
        self.assertEqual(self.writes,[701])

    def test_second_distinct_refusal_allows_a_third_request_but_not_a_return_to_any_earlier_request(self):
        from heideng_merchant.shop_copy_batch import publication_attempts
        self.reject[701]='1010300506'
        batch=self.plan((701,))
        refused=self.run_phase(batch,'bulk')
        root,freight,proof=self.correction(refused)
        self.reject[701]='10103001002'
        again=self.resume(batch,'--correction-evidence',str(proof),'--delivery-evidence',str(freight))
        self.assertEqual(again['rows'][0]['status'],'publication-rejected')
        self.assertEqual(self.writes,[701,701])
        dirs=publication_attempts(root)
        self.assertEqual([d.name for d in dirs],['publication','correction'])
        next_proof=read_json(proof)
        next_proof.update(originalBodySha256=read_json(dirs[-1]/'rejection.json')['payloadSha256'],
                          platformCode='10103001002',receipt=self.delivery.name,receiptSha256=file_sha(self.delivery))
        atomic_json(proof,next_proof)
        del self.reject[701]
        self.resume(batch,'--correction-evidence',str(proof),'--delivery-evidence',str(self.delivery))
        self.assertEqual(self.writes,[701,701])  # B -> A is still a replay of the original rejected request.
        final=self.root/'承诺修正.json'
        corrected=read_json(freight)
        corrected['target']['promiseTemplates'][0]['id']='192'
        atomic_json(final,corrected)
        next_proof.update(receipt=final.name,receiptSha256=file_sha(final),fields=['WarePromise'])
        atomic_json(proof,next_proof)
        self.blueprints[701]['productInfo']['logisticsInfo'].update(transportId=191,promiseId=192)
        last=self.resume(batch,'--correction-evidence',str(proof),'--delivery-evidence',str(final))
        self.assertEqual(last['uniqueMappedTargets'],1,last)
        self.assertEqual(self.writes,[701,701,701])
        dirs=publication_attempts(root)
        self.assertEqual(len(dirs),3)
        self.assertEqual(dirs[1].parent,dirs[2].parent)
        self.assertNotEqual(file_sha(dirs[0]/'publish-body.json'),file_sha(dirs[2]/'publish-body.json'))
        self.resume(batch,'--correction-evidence',str(proof))
        self.assertEqual(self.writes,[701,701,701])

    def test_two_simultaneous_resumes_cannot_dispatch_the_same_correction_twice(self):
        from argparse import Namespace
        from concurrent.futures import ThreadPoolExecutor
        from heideng_merchant import shop_copy_batch
        self.reject[701]='1010300506'
        batch=self.plan((701,))
        original=self.run_phase(batch,'bulk')
        _,updated,proof=self.correction(original)
        self.blueprints[701]['productInfo']['logisticsInfo']['transportId']=191
        del self.reject[701]
        def resume(_):
            args=Namespace(action='batch-resume',batch=batch,source_profile=SOURCE['profile'],source_config=self.config,
                           target_profile=TARGET['profile'],target_config=self.config,stop_id=None,authorization_ref=None,
                           delivery_evidence=updated,correction_evidence=proof)
            return shop_copy_batch.dispatch(args,self.entry)
        with ThreadPoolExecutor(2) as workers:
            results=list(workers.map(resume,range(2)))
        self.assertEqual(self.writes,[701,701])
        self.assertTrue(all(r['uniqueMappedTargets']==1 for r in results))
