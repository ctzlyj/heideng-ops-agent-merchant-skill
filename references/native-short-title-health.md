# 原范围短标题 native health 证据（C3 v2）

Agent 使用原持久 worker 的 `short-title-worker-effects`：同原 worker/importId/fingerprint，接收原 requestId 后读 command-status。此动作只读，不新增导入或修复批准；没有真实商家验收。完整正式短标题审核、门户与失败子计划仍为必须项，不能把 native 健康来源接通当整个目标完成。

## 真正读取的来源

原官方 ProductService health 列表 + `/rest/sp-product/v0/health-infos/{healthInfoId}` 详情。healthInfoId 是此次请求的原 SKU ID，SKU/productId 与原库存逐行核对；响应若带 healthScoreId 也必须与 SKU 相同，缺省时不凭名称/分值发明它。每个原兄弟 SKU 都查询，离线、缺行、未知不丢弃。全部源都不加 detectFactor 筛选，避免只见部分问题便认定没有短标题问题。

源前后各读取一次列表与全部详情，同时持有同线程真实 guard、原根范围和同店身份；列表完整分页、字段语义、原详情覆盖、前后一致性及列表/详情关联都核对。两次观察不代表服务端事务快照或CAS。不是反复刷新登录页，不能破坏原 uploaded DOM binding。

## 读报告而不误解

- `effectEvidenceVersion=2`：新版包含 nativeHealthEvidence。`nativeHealthSourcesVerified` 只说明原范围这部分健康来源通过本次核对。
- `targetHealthRequirementsSatisfied` 只说明目标 SKU 的该项短标题健康问题已不在完整关联原生问题中，**不代表**正式短标题审核、全部素材健康问题、门户或整体导入完成。healthVerified/formalAuditVerified/portalVerified/imported/retryAuthorized不会据此变true。
- 原 rows 的 healthScore/healthTitleIssue 仍是原列表事实；新 `nativeHealthDetailBefore` / `nativeHealthDetailAfter` 分开展示详情事实，不覆盖列表缺失或原 unknown。行历史通过 `short-title-import-rows --view effects` 分页，nativeHealthEvidenceHistorical=true。`status`/command-status 是最后观察或历史回执；currentNativeHealthSourceVerified仅当真实本次读取完成并核对当前owned context后返回，历史status为false。
- 原列表不含某兄弟 SKU 的行不被补造；独立详情可实际读到它，仍可在证据中看到列表与详情的区别。缺详情、分值缺失/错型、不完整问题结构、错SKU/product/healthId、前后变化或冲突均报告未核验，不能推断“没有问题”。
- sourceData可能包含签名URL，只在内存参与来源hash，不输出/持久化/追踪下载。新模式不调用任何图片、视频或公司模型。
- v1原件严格保留，后续v2不得降级删掉新来源证明；独立observation/receipt/head与活动native-prefix仍验证原件。新健康证据不解除原C3隔离、不自动重投失败、待审或未知任务。
