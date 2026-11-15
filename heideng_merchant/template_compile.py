"""Compile native rule templates from their own source declarations and original data.

No network, defaults, SKU invention or business submission happens here. The full
raw tree remains the authority; every produced leaf has an exact source binding.
"""
import copy,re
from .safety import SafetyError,redact
from .products import identifier
from .operations import digest
from .edit_contract import RULE_FIELDS,pointer,source_rows,converted,mapping,DTO_CONTAINERS

CONTRACT=1
META=RULE_FIELDS|{'tipsDetailList','validateTips','validateValueType','distZhChar'}
CRITICAL={'SkuId':'/skuId','SkuUUid':'/skuId','SkuVendorSku':'/outerId','SkuJdprice':'/priceInfo/jdPrice','SkuStockNum':'/stockNum'}
IMAGE_CODES={'WareSkuImg','LongImg','SkuMainImage','SkuRectangleImage','SkuGgtImage'}
SALE_KEYS={'attrValueAlias':'alias','attrValues':'attrValues','index':'index'}


def rule_components(rows):
    if not isinstance(rows,list):raise SafetyError('native-rule-components-array-required')
    result={}
    for rule in rows:
        code=_Compiler.checked(rule)
        if code in result:raise SafetyError('duplicate-native-rule-component')
        result[code]=rule
    return result


def code_is_attribute_group(rule):
    defs=rule.get('childrenComponents')
    return isinstance(defs,list) and bool(defs) and all(isinstance(r,dict) and re.fullmatch(r'prop-(?:product|sku)-[1-9][0-9]*',str(r.get('componentCode'))) for r in defs)


def compile_native(raw,detail):
    if not isinstance(raw,list) or not raw or not isinstance(detail,dict):
        raise SafetyError('native-rule-template-and-full-detail-required')
    if redact(raw)!=raw or redact(detail)!=detail:raise SafetyError('private-native-compilation-source-refused')
    engine=_Compiler(raw,detail)
    schema=[engine.component(r,'/'+str(i)) for i,r in enumerate(raw)]
    rule_components(schema)
    engine.check_attribute_coverage()
    return {'compilerContract':CONTRACT,'schema':schema,'bindings':engine.bindings,'saleSources':engine.sales}


class _Compiler:
    def __init__(self,raw,detail):
        self.detail=detail;self.rows=source_rows(detail);self.bindings=[];self.sales=[]
        self.attribute_expected={};self.attribute_used={}
        for sid,row in self.rows.items():
            for key in ('goodsAttrInfos','saleAttrs'):
                if key in row and row[key] not in (None,[]):self.register_attributes(sid,'/'+key,row[key])
        if not self.rows:raise SafetyError('native-compilation-complete-skus-required')
        skus=rule_components(raw).get('SKUS',{}).get('value')
        self.populated=isinstance(skus,list) and bool(skus)

    def register_attributes(self,sid,base,records):
        if not isinstance(records,list) or any(not isinstance(r,dict) for r in records):
            raise SafetyError('native-attribute-record-array-required')
        ids=[identifier(r.get('attrId')) for r in records]
        if len(ids)!=len(set(ids)):raise SafetyError('duplicate-native-attribute-record')
        key=(sid,base)
        if key in self.attribute_expected and self.attribute_expected[key]!=set(ids):
            raise SafetyError('native-attribute-source-census-conflict')
        self.attribute_expected[key]=set(ids);self.attribute_used.setdefault(key,set())

    def use_attribute(self,sid,source,aid):
        base=source.rsplit('/',1)[0]
        records=pointer(self.detail if sid is None else self.rows[sid],base)
        self.register_attributes(sid,base,records)
        self.attribute_used[(sid,base)].add(aid)

    def check_attribute_coverage(self):
        if any(self.attribute_used.get(k,set())!=ids for k,ids in self.attribute_expected.items()):
            raise SafetyError('original-native-attributes-not-fully-represented-by-schema-groups')

    def merge_rule(self,definition,value,sid=None,property_node=False):
        self.checked(definition,property_node);self.checked(value,property_node)
        for key in ('productDetailField','productDetailFieldType','josWareCommitFieldType'):
            if key in definition and key in value and definition[key]!=value[key]:
                if key!='productDetailField' or self.source(definition,sid)[0]!=self.source(value,sid)[0]:
                    raise SafetyError('conflicting-original-native-rule-declarations')
        out={**{k:copy.deepcopy(v) for k,v in definition.items() if k in META},**copy.deepcopy(value)}
        a=definition.get('extra',{});b=value.get('extra',{})
        if isinstance(a,dict) and isinstance(b,dict):
            if any(k in a and k in b and digest(a[k])!=digest(b[k]) for k in ('isColor','isStructure')):
                raise SafetyError('conflicting-original-native-attribute-classification')
            if a or b:out['extra']={**copy.deepcopy(a),**copy.deepcopy(b)}
        if not property_node:
            defs=definition.get('properties',[]);vals=value.get('properties',[])
            d={self.checked(p,True):p for p in defs};v={self.checked(p,True):p for p in vals}
            if len(d)!=len(defs) or len(v)!=len(vals):raise SafetyError('duplicate-original-native-property')
            if defs or vals:
                out['properties']=[self.merge_rule(d.get(p['key'],{'key':p['key']}),p,sid,True) for p in vals]+[copy.deepcopy(p) for p in defs if p['key'] not in v]
        return out

    def children(self,rule,sid=None):
        defs=rule.get('childrenComponents') or []
        values=rule.get('value')
        if self.populated and isinstance(values,list) and values:
            if not isinstance(defs,list):raise SafetyError('native-child-definitions-array-required')
            if defs:
                codes=[self.checked(r) for r in defs]
                by_code={self.checked(r):r for r in defs}
                if len(set(codes))!=len(codes):
                    if not all(c=='img' for c in codes) or len(defs)!=len(values):raise SafetyError('duplicate-native-child-rule')
                    return [self.merge_rule(defs[i],r,sid) for i,r in enumerate(values)]
                return [self.merge_rule(by_code.get(self.checked(r),{'componentCode':r['componentCode']}),r,sid) for r in values]
            return values
        return defs or values

    @staticmethod
    def checked(rule,property_node=False):
        if not isinstance(rule,dict):raise SafetyError('native-rule-object-required')
        fields={'key','value'} if property_node else {'componentCode','value','properties'}
        if set(rule)-fields-META:raise SafetyError('unreviewed-native-rule-field-not-silently-dropped')
        name=rule.get('key' if property_node else 'componentCode')
        if not isinstance(name,str) or not name:raise SafetyError('native-rule-field-name-required')
        return name

    def source(self,rule,sid=None,fallback=None):
        hint=rule.get('productDetailField')
        if hint is not None:
            if not isinstance(hint,str) or not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*',hint):
                raise SafetyError('original-native-field-declaration-required')
            parts=hint.split('.')
            if sid is not None:
                if parts[:2]==['productInfo','skuList']:parts=parts[2:]
                elif parts[0]=='skuList':parts=parts[1:]
            elif parts[0]=='skuList':raise SafetyError('native-sku-field-needs-real-selector')
            source='/'+('/'.join(parts))
        elif fallback is not None:source=fallback
        else:raise SafetyError('native-rule-field-has-no-proven-source: '+str(rule.get('componentCode',rule.get('key','unknown'))))
        value=pointer(self.detail if sid is None else self.rows[sid],source)
        return source,value

    def emit(self,rule,source,sid,path,mode='identity',*,property_node=False,prototype=False):
        name=self.checked(rule,property_node)
        original=pointer(self.detail if sid is None else self.rows[sid],source)
        value=converted(original,mode)
        if self.populated and not prototype and 'value' in rule and digest(converted(rule['value'],mode))!=digest(value):
            raise SafetyError('populated-native-value-disagrees-with-original-source')
        out={'key' if property_node else 'componentCode':name,'value':copy.deepcopy(value)}
        parts=source.split('/')[1:]
        if not all(re.fullmatch(r'[A-Za-z0-9_]+',p) for p in parts):raise SafetyError('native-source-field-cannot-be-declared-without-loss')
        out['productDetailField']=('skuList.' if sid else '')+'.'.join(parts)
        if 'josWareCommitFieldType' in rule:out['josWareCommitFieldType']=rule['josWareCommitFieldType']
        self.bindings.append({'schemaPointer':path+'/value','sourcePointer':source,'skuId':sid,'conversion':mode})
        return out

    def properties(self,rule,path,sid=None,base=None,*,prototype=False,image=False):
        props=rule.get('properties',[])
        if not isinstance(props,list):raise SafetyError('native-properties-array-required')
        names=[self.checked(p,True) for p in props]
        if len(names)!=len(set(names)):raise SafetyError('duplicate-native-property')
        result=[]
        for i,p in enumerate(props):
            source,value=self.source(p,sid,base+'/'+p['key'] if base is not None else None)
            mode='jfs' if image and p['key']=='imgUrl' else 'html' if p['key']=='desc' and isinstance(value,str) else 'identity'
            result.append(self.emit(p,source,sid,path+'/properties/'+str(i),mode,property_node=True,prototype=prototype))
        return result

    def image(self,rule,path,sid=None):
        if 'productDetailField' not in rule:
            values=rule.get('value')
            if not isinstance(values,list):raise SafetyError('image-container-needs-native-source-declaration')
            return {'componentCode':rule['componentCode'],'value':[self.component(v,path+'/value/'+str(i),sid,image=True) for i,v in enumerate(values)]}
        base,value=self.source(rule,sid)
        if isinstance(value,dict):records=[(base,value)]
        elif isinstance(value,list) and all(isinstance(v,dict) for v in value):records=[(base+'/'+str(i),v) for i,v in enumerate(value)]
        else:raise SafetyError('original-native-image-records-required')
        prototypes=self.children(rule,sid)
        if not isinstance(prototypes,list) or not prototypes:raise SafetyError('native-image-child-rule-required')
        proto=prototypes[0];self.checked(proto)
        if proto['componentCode']!='img':raise SafetyError('native-image-img-component-required')
        if len(prototypes)!=1 and len(prototypes)!=len(records):raise SafetyError('native-image-rule-range-unproven')
        values=[]
        for i,(source,record) in enumerate(records):
            r=copy.deepcopy(prototypes[i] if len(prototypes)>1 else proto)
            names=[self.checked(p,True) for p in r.get('properties',[])]
            if len(names)!=len(set(names)):raise SafetyError('duplicate-native-image-property')
            # Preserve unknown native image business values rather than dropping them.
            r['properties']=r.get('properties',[])+[{'key':k} for k in sorted(record) if k not in names]
            entry={'componentCode':'img','properties':self.properties(r,path+'/value/'+str(i),sid,source,prototype=not self.populated,image=True)}
            if 'value' in r:
                ref,_=self.source(r,sid)
                emitted=self.emit(r,ref,sid,path+'/value/'+str(i),prototype=not self.populated)
                entry.update({k:v for k,v in emitted.items() if k!='componentCode'})
            values.append(entry)
        return {'componentCode':rule['componentCode'],'value':values}

    def sale(self,rule,path,sid):
        prototypes=self.children(rule,sid)
        if not isinstance(prototypes,list):raise SafetyError('native-sale-child-rules-required')
        rule_components(prototypes);native={}
        if 'productDetailField' in rule:
            base,records=self.source(rule,sid)
            if not isinstance(records,list):raise SafetyError('native-sale-source-array-required')
            for i,r in enumerate(records):
                aid=identifier(r.get('attrId')) if isinstance(r,dict) else None
                if aid in native:raise SafetyError('duplicate-native-sale-attribute')
                native[aid]=(base+'/'+str(i),r)
            self.register_attributes(sid,base,records)
            wanted={r['componentCode'].removeprefix('sale-prop-') for r in prototypes}
            if not wanted<=set(native):raise SafetyError('complete-native-sale-attribute-census-required')
        values=[]
        for i,r in enumerate(prototypes):
            code=self.checked(r)
            if not re.fullmatch(r'sale-prop-[1-9][0-9]*',code):raise SafetyError('native-sale-attribute-code-required')
            aid=code.removeprefix('sale-prop-');source,record=native.get(aid,(None,None))
            if source is None:
                # Populated templates can carry exact child field declarations.
                for p in r.get('properties',[]):
                    if 'productDetailField' not in p:continue
                    candidate,_=self.source(p,sid);candidate=candidate.rsplit('/',1)[0]
                    record=pointer(self.rows[sid],candidate)
                    if isinstance(record,dict) and str(record.get('attrId'))==aid:source=candidate;break
                if source is None:raise SafetyError('actual-native-sale-record-declaration-required')
            self.use_attribute(sid,source,aid)
            self.sales.append({'skuId':sid,'componentCode':code,'sourcePointer':source})
            out={'componentCode':code,'properties':[]}
            if 'extra' in r:out['extra']=copy.deepcopy(r['extra'])
            if 'value' in r:
                ref,_=self.source(r,sid)
                emitted=self.emit(r,ref,sid,path+'/value/'+str(i),prototype=not self.populated)
                out.update({k:v for k,v in emitted.items() if k!='componentCode'})
            props=r.get('properties',[]);names=[self.checked(p,True) for p in props]
            if len(names)!=len(set(names)):raise SafetyError('duplicate-native-sale-property')
            known={'attrId','alias','mappingId','attrValues','index'}
            props=props+[{'key':k} for k in sorted(record) if k not in known and k not in names]
            for j,p in enumerate(props):
                key=self.checked(p,True);mode='identity'
                if key=='mappingId':
                    field='attrValues' if record.get('mappingId') in (None,'') else 'mappingId'
                    ref=source+'/'+field;mode='string';mapping(record)
                else:ref,_=self.source(p,sid,source+'/'+SALE_KEYS.get(key,key))
                out['properties'].append(self.emit(p,ref,sid,path+'/value/'+str(i)+'/properties/'+str(j),mode,property_node=True,prototype=not self.populated))
            values.append(out)
        return {'componentCode':'VenderCategoryValue','value':values}

    def attributes(self,rule,path,sid=None):
        base,records=self.source(rule,sid)
        if not isinstance(records,list) or any(not isinstance(r,dict) for r in records):
            raise SafetyError('native-product-attribute-records-required')
        prototypes=self.children(rule,sid);rules=rule_components(prototypes)
        native={}
        for i,record in enumerate(records):
            aid=identifier(record.get('attrId'))
            if aid in native:raise SafetyError('duplicate-native-product-attribute')
            native[aid]=(base+'/'+str(i),record)
        self.register_attributes(sid,base,records)
        if {re.sub(r'^prop-(?:product|sku)-','',code) for code in rules}-set(native):
            raise SafetyError('complete-native-product-attribute-census-required')
        values=[]
        for i,r in enumerate(prototypes):
            aid=re.sub(r'^prop-(?:product|sku)-','',r['componentCode']);source,record=native[aid];self.use_attribute(sid,source,aid)
            shared={'componentCode':r['componentCode'],'properties':[p for p in rule.get('properties',[]) if 'value' not in p and 'productDetailField' not in p]}
            child=self.merge_rule(shared,r,sid);names=[self.checked(p,True) for p in child.get('properties',[])]
            child['properties']=child.get('properties',[])+[{'key':k} for k in sorted(record) if k not in names and k!='attrId']
            entry={'componentCode':r['componentCode'],
                   'properties':self.properties(child,path+'/value/'+str(i),sid,source,prototype=not self.populated)}
            if 'value' in r:
                ref,_=self.source(r,sid)
                emitted=self.emit(r,ref,sid,path+'/value/'+str(i),prototype=not self.populated)
                entry.update({k:v for k,v in emitted.items() if k!='componentCode'})
            values.append(entry)
        return {'componentCode':rule['componentCode'],'value':values,
                'childrenComponents':[{'componentCode':r['componentCode']} for r in prototypes]}

    def skus(self,rule,path):
        values=rule.get('value')
        if values:
            if not isinstance(values,list):raise SafetyError('native-sku-rows-array-required')
            rows=[];seen=set()
            for i,row in enumerate(values):
                self.checked(row)
                if row['componentCode']!='SKU':raise SafetyError('native-SKU-component-required')
                fields=rule_components(row.get('value',[]));sid=identifier(fields.get('SkuId',{}).get('value'));uid=identifier(fields.get('SkuUUid',{}).get('value'))
                if sid!=uid or sid not in self.rows or sid in seen:raise SafetyError('native-real-sku-id-and-uuid-required')
                seen.add(sid);entry=self.sku(row['value'],path+'/value/'+str(i),sid,False)
                if 'properties' in row:entry['properties']=self.properties(row,path+'/value/'+str(i),sid)
                rows.append(entry)
            if seen!=set(self.rows):raise SafetyError('complete-native-sku-range-required')
        else:
            prototypes=rule.get('childrenComponents')
            if not isinstance(prototypes,list):raise SafetyError('native-sku-child-rules-required')
            rule_components(prototypes);rows=[self.sku(prototypes,path+'/value/'+str(i),sid,True) for i,sid in enumerate(self.rows)]
        return {'componentCode':'SKUS','value':rows}

    def sku(self,fields,path,sid,prototype):
        by_code=rule_components(fields)
        if not {'SkuVendorSku','SkuJdprice','SkuStockNum'}<=set(by_code):raise SafetyError('native-critical-sku-component-rules-required')
        order=['SkuId','SkuUUid']+[r['componentCode'] for r in fields if r['componentCode'] not in ('SkuId','SkuUUid')]
        values=[]
        for i,code in enumerate(order):
            r=by_code.get(code,{'componentCode':code})
            values.append(self.component(r,path+'/value/'+str(i),sid,prototype=prototype))
        return {'componentCode':'SKU','value':values}

    def component(self,rule,path,sid=None,*,prototype=False,image=False):
        out=self._component(rule,path,sid,prototype=prototype,image=image)
        if 'properties' in rule and 'properties' not in out:
            if code_is_attribute_group(rule):
                own={**rule,'properties':[p for p in rule['properties'] if 'value' in p or 'productDetailField' in p]}
                if own['properties']:out['properties']=self.properties(own,path,sid,prototype=prototype,image=image)
            else:out['properties']=self.properties(rule,path,sid,prototype=prototype,image=image)
        return out

    def _component(self,rule,path,sid=None,*,prototype=False,image=False):
        code=self.checked(rule)
        if code=='SKUS':return self.skus(rule,path)
        if code in IMAGE_CODES:return self.image(rule,path,sid)
        if code=='VenderCategoryValue':
            if sid is None:raise SafetyError('native-sale-fields-need-real-sku-selector')
            return self.sale(rule,path,sid)
        if code in CRITICAL:
            if sid is None:raise SafetyError('native-critical-field-needs-real-sku-selector')
            source,value=self.source(rule,sid,CRITICAL[code])
            if source!=CRITICAL[code]:raise SafetyError('native-critical-sku-field-declaration-mismatch')
            return self.emit(rule,source,sid,path,'string' if code in ('SkuId','SkuUUid') else 'identity',prototype=prototype)
        definitions=rule.get('childrenComponents')
        if 'productDetailField' in rule and isinstance(definitions,list) and definitions and all(isinstance(r,dict) and re.fullmatch(r'prop-(?:product|sku)-[1-9][0-9]*',str(r.get('componentCode'))) for r in definitions):
            return self.attributes(rule,path,sid)
        if 'productDetailField' in rule:
            source,value=self.source(rule,sid)
            return self.emit(rule,source,sid,path,prototype=prototype)
        values=rule.get('value')
        children=values if self.populated and isinstance(values,list) and values else definitions or values
        if (definitions or code in DTO_CONTAINERS) and isinstance(children,list) and children and all(isinstance(r,dict) and 'componentCode' in r for r in children):
            # Structural children are explicit rule containers, never opaque blobs.
            rule_components(children)
            return {'componentCode':code,'value':[self.component(r,path+'/value/'+str(i),sid,prototype=prototype,image=image) for i,r in enumerate(children)],
                    'childrenComponents':[{'componentCode':r['componentCode']} for r in children]}
        if 'properties' in rule:
            if 'value' in rule:raise SafetyError('native-component-value-needs-own-source-declaration')
            return {'componentCode':code,'properties':self.properties(rule,path,sid,prototype=prototype,image=image)}
        raise SafetyError('native-rule-field-has-no-proven-source: '+code)


def compilation_proof(raw,detail,result,original_id,original_fingerprint):
    import hashlib
    from pathlib import Path
    source=Path(__file__).read_bytes().replace(b'\r\n',b'\n')
    return {'contract':CONTRACT,'compilerSourceSha256':hashlib.sha256(source).hexdigest(),
            'originalCaptureId':original_id,'originalCaptureFingerprint':original_fingerprint,
            'rawSchemaHash':digest(raw),'detailHash':digest(detail),'schemaHash':digest(result['schema']),
            'bindingsHash':digest(result['bindings']),'saleSourcesHash':digest(result['saleSources'])}


def verify_compiled_scope(scope):
    proof=scope.get('schemaCompiler')
    if not isinstance(proof,dict) or not isinstance(scope.get('rawSchema'),list):
        raise SafetyError('native-compiled-source-proof-required')
    result=compile_native(scope['rawSchema'],scope['productDetail'])
    expected=compilation_proof(scope['rawSchema'],scope['productDetail'],result,
                               proof.get('originalCaptureId'),proof.get('originalCaptureFingerprint'))
    if digest(proof)!=digest(expected) or digest(scope['schema'])!=digest(result['schema']):
        raise SafetyError('native-compiled-record-does-not-match-original-sources')
    return result
