"""Field regressions through registered shop-copy commands, with isolated official-shop fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from heideng_merchant import owned_product_copy as copying
from heideng_merchant import shop_copy_batch as batches
from heideng_merchant.safety import atomic_json,read_json
from tests import test_shop_copy_batch, test_shop_copy_repair
from tests.test_owned_copy_decisions import template_for_text
from tests.test_owned_product_copy import SOURCE,TARGET


class RepairFieldTests(unittest.TestCase):
    def setUp(self):
        self.f=test_shop_copy_repair.CodeRepairEntryTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def refreeze(self):
        f=self.f
        f.frozen=copying.freeze_copy(SOURCE,TARGET,f.source)
        f.revision=f.root/'revisions'/f.frozen['sha256'][:24]
        atomic_json(f.revision/'source.json',f.frozen)
        pointer=read_json(f.root/'current.json')
        pointer['revision']=f.frozen['sha256']
        atomic_json(f.root/'current.json',pointer)

    def test_explicit_empty_source_code_clears_only_when_optional(self):
        f=self.f
        f.source['skuList'][0]['outerId']=''
        self.refreeze()
        real_get=f.api.get.side_effect
        def required(skill,url,params):
            reply=real_get(skill,url,params)
            if url.endswith('/product-schemas') and 'productId' not in params:
                code=reply['data'][0]['componentList'][0]['childrenComponents'][0]
                code.update(validateRule=[{'validateType':'required','validateRule':'true'}])
            return reply
        with patch.object(f.api,'get',side_effect=required):
            result=f.confirm()
            self.assertEqual(result['status'],'needs-edit-template',result)
            self.assertIn('非空',' '.join(result['reasons']))
            self.assertEqual(f.writes,[])
        result=f.confirm()
        self.assertEqual(result['status'],'sku-codes-verified',result)
        self.assertEqual(result['online']['observedCodes'],{'301':'','302':'CODE/b'})
        self.assertEqual(len(f.writes),1)

    def test_absent_source_field_does_not_clear_target(self):
        f=self.f
        del f.source['skuList'][0]['outerId']
        self.refreeze()
        result=f.confirm()
        self.assertEqual(result['status'],'needs-repair-evidence')
        self.assertEqual(f.writes,[])

    def configure_aliases(self,structured):
        f=self.f
        for detail in (f.source,f.online,f.application):
            for row in detail['skuList']:
                axis=row['saleAttrs'][0]
                long=axis['attrValueAlias']+'色柔光灯'
                if detail is f.source:axis['attrValueAlias']=long
                if structured:
                    key={'白':710,'蓝':720}[long[0]]
                    axis['templateSkuProps']=[{'id':'finish','value':long,'valueId':key if detail is not f.source else key-600}]
        self.refreeze()
        ref={'shopIdentity':TARGET,'category':{'id':91},'schema':{'componentList':[{'componentCode':'sale-prop-88'}]},
             'structuredSaleTemplates':{'88':template_for_text('88',{'白色柔光灯':710,'蓝色柔光灯':720})}}
        self.enterContext(patch.object(f.entry,'reference',return_value=ref))

    def test_distinct_full_target_option_tuples_can_match_truncated_display_aliases(self):
        self.configure_aliases(True)
        f=self.f
        schema=test_shop_copy_repair.live_schema(f.application)
        attrs={r['skuId']:r['saleAttrs'][0] for r in f.application['skuList']}
        for group in schema[-1]['value']:
            fields={x['componentCode']:x for x in group['value']}
            axis=attrs[fields['SkuId']['value']]
            fields['VenderCategoryValue']['value'][0]['properties'].append({
                'key':'templateSkuProps','value':json.dumps(axis['templateSkuProps'])})
        f.draft_schema=schema
        result=f.confirm()
        self.assertEqual(result['status'],'sku-codes-verified',result)
        self.assertEqual(result['online']['observedCodes'],{'301':'00001','302':'CODE/b'})

    def test_display_prefix_only_is_not_a_writable_pair(self):
        self.configure_aliases(False)
        result=self.f.confirm()
        self.assertEqual(result['status'],'needs-repair-evidence')
        self.assertEqual(self.f.writes,[])

    def test_duplicate_complete_target_tuples_do_not_disambiguate_by_label_or_code(self):
        self.configure_aliases(True)
        f=self.f
        for detail in (f.application,f.online):
            detail['skuList'][1]['saleAttrs'][0]['templateSkuProps']=deepcopy(
                detail['skuList'][0]['saleAttrs'][0]['templateSkuProps'])
        self.assertEqual(f.confirm()['status'],'needs-repair-evidence')
        self.assertEqual(f.writes,[])


class BatchFieldTests(unittest.TestCase):
    def setUp(self):
        self.f=test_shop_copy_batch.BatchCopyTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_store_permission_hold_survives_skips_and_a_phase_without_a_representative(self):
        f=self.f
        f.reject.update({701:'99904030007',703:'99904030007'})
        # The pilot by itself need not be a representative of either refused category.
        batch=f.plan((704,701,703))
        normal=f.entry.prepare
        def cannot_prepare_first(folder,frozen,target,args):
            if str(frozen['sourceProductId'])=='704':
                return {'status':'needs-evidence','missing':['合成样品缺商品资料']}
            return normal(folder,frozen,target,args)
        with patch.object(f.entry,'prepare',side_effect=cannot_prepare_first):
            self.assertEqual(f.run_phase(batch,'bulk')['hold']['reason'],'repeated-official-permission-refusal')
        self.assertEqual(f.writes,[701,703])
        original=list(f.writes)
        f.command('batch-skip','--batch',batch,'--source-product-id','701','--source-product-id','703')
        self.assertTrue(f.resume(batch)['hold']['active'])
        self.assertEqual(f.run_phase(batch,'pilot')['status'],'batch-held')
        self.assertEqual(f.writes,original)

    def test_excluded_permission_representatives_do_not_open_third_item(self):
        f=self.f
        f.reject.update({701:'99904030007',703:'99904030007'})
        batch=f.plan((701,703,704))
        self.assertEqual(f.run_phase(batch,'bulk')['status'],'batch-held')
        f.command('batch-skip','--batch',batch,'--source-product-id','701','--source-product-id','703')
        result=f.resume(batch)
        self.assertEqual((result['status'],result['hold']['reason']),('batch-held','repeated-official-permission-refusal'))
        self.assertEqual(f.writes,[701,703])
        self.assertEqual(f.validations,[701,703])

    def test_skipping_uncertain_creation_preserves_global_hold_and_original_receipt(self):
        f=self.f
        f.lost.add(701)
        batch=f.plan((701,703))
        held=f.run_phase(batch,'bulk')
        self.assertEqual(held['hold']['reason'],'submission-needs-reconciliation')
        f.command('batch-skip','--batch',batch,'--source-product-id','701')
        self.assertEqual(f.resume(batch)['status'],'batch-held')
        self.assertEqual(f.writes,[701])
        self.assertEqual(f.validations,[701])

    def test_only_successful_permission_correction_can_unlock_store_hold(self):
        f=self.f
        f.reject.update({701:'99904030007',703:'99904030007'})
        batch=f.plan((701,703,704))
        held=f.run_phase(batch,'bulk')
        task,delivery,proof=f.correction(held)
        refusal=read_json(task/'publication/rejection.json')
        value=read_json(proof);value['platformCode']='99904030007';atomic_json(proof,value)
        del f.reject[701]
        for pid in (701,704):
            f.blueprints[pid]['productInfo']['logisticsInfo']['transportId']=191
        args=('--correction-evidence',str(proof),'--delivery-evidence',str(delivery))
        self.assertEqual(f.resume(batch,*args)['status'],'batch-held')
        self.assertEqual(f.writes,[701,703])
        grant=f.root/'合成权限回执.json'
        atomic_json(grant,{'shop':TARGET,'action':'POST.sp-product.v0.product-applies','grant':'fixture'})
        from heideng_merchant.safety import file_sha
        value['permissionChange']={'action':'POST.sp-product.v0.product-applies','shop':TARGET,'from':'denied','to':'granted',
                                   'receipt':grant.name,'receiptSha256':file_sha(grant),'checkedAt':refusal['observedAt']+1}
        atomic_json(proof,value)
        result=f.resume(batch,*args)
        self.assertFalse(result['hold'].get('active'),result)
        self.assertEqual(f.writes,[701,703,701,704])

    def test_diagnose_uses_exact_rejected_application_without_live_target(self):
        f=self.f
        f.applies[9701]={**deepcopy(f.blueprints[701]),'applyInfo':{'applyId':9701,'draftComputeStatus':3}}
        f.apply_rows=[{'productId':1701,'applyId':9711,'auditReason':'另一次申请的原因'},
                      {'productId':1701,'applyId':9701,'auditReason':'包装尺寸与类目不符'},
                      {'productId':1703,'applyId':9701,'auditReason':'别件商品'}]
        r=f.command('diagnose-application',*f.dst,'--product-id','1701','--apply-id','9701')
        self.assertEqual((r['auditState'],r['listingEvidence'],r['platformWrites']),('rejected','live-product-unverified',0))
        self.assertEqual(r['rejection']['auditReason'],'包装尺寸与类目不符')
        f.apply_rows=[{'productId':1701,'auditReason':'只按商品筛到的最新文字'}]
        r=f.command('diagnose-application',*f.dst,'--product-id','1701','--apply-id','9701')
        self.assertNotIn('auditReason',r['rejection'])
        self.assertEqual(r['latestProductReview']['auditReason'],'只按商品筛到的最新文字')
        self.assertFalse(r['latestProductReview']['originalApplicationVerified'])
        f.applies[9701]['shopId']='99999'
        self.assertFalse(f.command('diagnose-application',*f.dst,'--product-id','1701','--apply-id','9701')['ok'])
        self.assertEqual(f.writes,[])

    def test_original_reason_cannot_be_inferred_after_scope_fallback(self):
        f=self.f
        f.applies[9701]={**deepcopy(f.blueprints[701]),'applyInfo':{'applyId':9701,'draftComputeStatus':3}}
        original=f.entry.api.get.side_effect
        requests=[]
        def narrow(skill,url,params=None):
            if url.endswith('/product-applies'):
                requests.append(params['scopeSet'])
                if 'applyId' in params['scopeSet']:
                    return f.entry.api.parse_response(json.dumps({'success':False,'errorList':[{'code':'1010300506'}]}))
                return {'success':True,'data':[{k:v for k,v in {'productId':1701,'auditReason':'最新记录'}.items()
                                                if k in params['scopeSet']}]}
            return original(skill,url,params)
        with patch.object(f.entry.api,'get',side_effect=narrow):
            result=f.command('diagnose-application',*f.dst,'--product-id','1701','--apply-id','9701')
        self.assertEqual(len(requests),2)
        self.assertNotIn('auditReason',result['rejection'])
        self.assertEqual(result['latestProductReview']['auditReason'],'最新记录')
        self.assertEqual(f.writes,[])

    def test_older_cli_refusing_both_optional_fields_returns_only_product_level_reason(self):
        f=self.f
        f.applies[1701]={**deepcopy(f.blueprints[701]),'applyInfo':{'draftComputeStatus':3}}
        original=f.entry.api.get.side_effect
        scopes=[]
        def legacy(skill,url,params=None):
            if url.endswith('/product-applies'):
                scopes.append(params['scopeSet'])
                if {'applyId','auditReason'}.intersection(params['scopeSet']):
                    raise f.entry.api.JdoError('合成 CLI 字段不受支持')
                return {'success':True,'data':[{'productId':1701,'keeperReason':'最新商品资料需修改'}]}
            return original(skill,url,params)
        with patch.object(f.entry.api,'get',side_effect=legacy):
            result=f.command('diagnose-application',*f.dst,'--product-id','1701')
        self.assertEqual(len(scopes),3)
        self.assertNotIn('applyId',result['rejection'])
        self.assertNotIn('keeperReason',result['rejection'])
        self.assertEqual(result['latestProductReview']['keeperReason'],'最新商品资料需修改')
        self.assertEqual(f.writes,[])

    def test_batch_uses_original_application_when_live_detail_has_a_different_pending_draft(self):
        f=self.f
        batch=f.plan((701,703))
        f.run_phase(batch,'pilot')
        f.destinations[1701]['applyInfo']={'applyId':9711,'draftComputeStatus':1}
        f.applies[9701]['applyInfo']['draftComputeStatus']=3
        f.apply_rows=[{'productId':1701,'applyId':9711,'auditReason':'另一份申请'},
                      {'productId':1701,'applyId':9701,'keeperReason':'原包装信息需核对'}]
        result=f.run_phase(batch,'bulk')
        review=result['rows'][0]['comparison']
        self.assertEqual(result['hold']['reason'],'application-rejected')
        self.assertEqual(review['rejection']['keeperReason'],'原包装信息需核对')
        self.assertEqual(review['latestProductReview']['auditReason'],'另一份申请')
        self.assertEqual(f.writes,[701])

    def existing_batch(self):
        f=self.f
        for sid in (701,702,703,704):
            f.destinations[sid+1000]=deepcopy(f.blueprints[sid])
        f.destinations[9999]=deepcopy(f.blueprints[704])
        f.destinations[9999]['productInfo']['productId']=9999
        path=f.root/'known-mapping.json'
        atomic_json(path,{str(s):str(s+1000) for s in (701,702,703,704)})
        batch=f.plan((701,702,703,704),'--existing-map',str(path))
        f.command('batch-skip','--batch',batch,'--source-product-id','702','--reason','商家保留原商品')
        return batch

    def test_status_export_and_unstarted_existing_census_respect_frozen_scope(self):
        f=self.f
        batch=self.existing_batch()
        output=f.root/'report.json'
        r=f.command('batch-status','--batch',batch,'--output',str(output))
        self.assertEqual(read_json(output),r)
        self.assertEqual(r['excludedSourceProductIds'],['702'])
        scope=batches.directory(batch)/'scope.json';before=scope.read_bytes()
        self.assertFalse(f.command('batch-status','--batch',batch,'--output',str(scope))['ok'])
        self.assertEqual(scope.read_bytes(),before)
        c=f.command('batch-census','--batch',batch,*f.dst)
        self.assertEqual(c['mappedOnSaleIds'],['1701','1703','1704'])
        self.assertEqual(c['skippedTargetIds'],['1702'])
        self.assertEqual(c['onSaleOutsideBatch'],['9999'])
        self.assertEqual(f.writes,[])

    def test_batch_materials_dispatches_only_unique_active_known_pairs_and_keeps_unknown(self):
        f=self.f
        batch=self.existing_batch()
        root=batches.directory(batch)
        atomic_json(batches._record_path(root,'703'),{'sourceProductId':'703','targetProductId':'1701','status':'submitted'})
        atomic_json(batches._record_path(root,'704'),{'sourceProductId':'704','targetProductId':'1704','status':'submission-needs-reconciliation'})
        with patch('heideng_merchant.shop_copy_materials.handle') as child:
            result=f.command('batch-materials','--batch',batch,*f.src,*f.dst,'--confirm','FILL_MISSING_COPY_MATERIALS')
            self.assertFalse(result['ok'])
            self.assertEqual(result['unresolvedProducts'],3)
            child.assert_not_called()
            self.assertEqual(result['migrationCounts']['skipped-by-merchant'],1)
            atomic_json(batches._record_path(root,'704'),{'sourceProductId':'704','targetProductId':'1704','status':'submitted'})
            child.return_value={'ok':False,'migrationStatus':'awaiting-material-receipt','targetHealthStatus':'unknown'}
            result=f.command('batch-materials','--batch',batch,*f.src,*f.dst,'--source-product-id','704',
                             '--confirm','FILL_MISSING_COPY_MATERIALS')
            self.assertFalse(result['ok'])
            self.assertEqual(result['unresolvedProducts'],1)
            self.assertEqual(len(child.call_args_list),1)
            args=child.call_args.args[0]
            self.assertEqual((args.source_product_id,args.target_product_id),(704,1704))
            self.assertEqual(result['healthCounts'],{'unknown':1})
            self.assertFalse(f.command('batch-materials','--batch',batch,*f.src,*f.dst,'--source-product-id','9999')['ok'])
            self.assertEqual(len(child.call_args_list),1)
        self.assertEqual(f.writes,[])

    def test_material_audit_cannot_count_unmapped_rows_complete(self):
        f=self.f
        batch=f.plan((701,702))
        with patch('heideng_merchant.shop_copy_materials.handle') as child:
            result=f.command('batch-materials','--batch',batch,*f.src,*f.dst,'--health')
            self.assertFalse(result['ok'])
            self.assertEqual(result['unresolvedProducts'],2)
            child.assert_not_called()

    def test_history_census_retains_conflicting_links_and_preserves_requested_denominators(self):
        f=self.f
        f.destinations[1701]=deepcopy(f.blueprints[701])
        history=f.root/'旧店铺任务'
        def member(prefix,source,payload):
            atomic_json(history/prefix/str(source)/'state'/'receipt.json',{'store':TARGET,'sourceSpu':source,**payload})
        member('batch1',701,{'productId':1701,'verification':{'productId':1702}})
        member('batch2',702,{'productId':1701})
        member('batch3',703,{'store':SOURCE,'productId':1701})
        result=f.command('history-census','--history-dir',str(history),*f.dst,
                         '--target-product-id','1701','--target-product-id','1701','--target-product-id','1702')
        self.assertEqual((result['requestedRowCount'],result['uniqueTargetCount'],result['platformWrites']),(3,2,0))
        a,b=result['rows']
        self.assertEqual(set(a['sourceCandidates']),{'701','702'})
        self.assertEqual(a['otherTargetsForSameSource'],{'701':['1702']})
        self.assertTrue(a['foundInProductCatalogue'])
        self.assertFalse(b['foundInProductCatalogue'])
        self.assertEqual(result['unusableReceipts'][0]['reason'],'other-or-unverified-shop')
        self.assertEqual(f.writes,[])

    def test_history_census_reads_legacy_verification_file_and_keeps_title_siblings_as_hints(self):
        f=self.f
        history=f.root/'历史任务'
        shared=history/'batch'
        check=shared/'201_合成样品'/'.pipeline'/'publish'/'verification.json'
        atomic_json(check,{'productId':1801,'ok':True})
        state={'store':TARGET,'sourceSku':201,'sourceSpu':701,'productId':1701,
               'applyId':9701,'verification':str(check)}
        atomic_json(shared/'state'/'201.json',state)
        outside=f.root/'other'/'verification.json'
        atomic_json(outside,{'productId':7777})
        atomic_json(history/'batch2'/'702'/'state'/'202.json',{**state,'sourceSku':202,'sourceSpu':702,
                    'productId':1702,'verification':str(outside)})
        for tid in (1701,1801,1901):
            f.destinations[tid]=deepcopy(f.blueprints[701])
            f.destinations[tid]['productInfo']['productId']=tid
        result=f.command('history-census','--history-dir',str(history),*f.dst)
        rows={r['targetProductId']:r for r in result['rows']}
        self.assertEqual(set(rows),{'1701','1702','1801','1901'})
        self.assertEqual(rows['1701']['sourceCandidates']['701'][0]['field'],'publication')
        verified=rows['1801']['sourceCandidates']['701'][0]
        self.assertEqual(verified['field'],'verification')
        self.assertEqual(verified['file'],check.relative_to(history).as_posix())
        self.assertIsNone(verified['applyId'])
        self.assertEqual(rows['1801']['otherTargetsForSameSource'],{'701':['1701']})
        self.assertEqual(rows['1901']['sourceCandidates'],{})
        hints=rows['1901']['unverifiedSiblingHints']
        self.assertEqual({r['targetProductId'] for r in hints},{'1701','1801'})
        self.assertTrue(all(r['requiresIndependentProductAndSkuCheck'] for r in hints))
        self.assertEqual(result['unusableReceipts'][0]['reason'],'unreadable-verification')
        self.assertEqual(result['platformWrites'],0)
        self.assertEqual(f.writes,[])
