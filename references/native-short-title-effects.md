# 原范围实际短标题回读与持久化证据（C3 部分来源，完整闭环未完成）

Agent 在同一原生商家会话调用 `ShortTitleImports.collect_effects(importId, ownedBrowser)`。商家不手工提供“结果证明”，也不上传替代回读文件。读取复用真实仍持有的 install.lock 和原 import 锁；CLI `short-title-import-rows --view effects` 仅历史分页，不刷新授权或读取当前店铺。

## 独立事实

- 使用已审计官方 POP 商品 detail 中的 `skuList[].features.shortTitle`；仅该准确字段。长标题、skuName、模板控件和 hasShortTitle 不能替代实际值。
- 原 plan/audit 的全部兄弟 SKU 都保留，包括当时非在售、当前已下架及当前 detail 缺失的行。新增当前 SKU 不进入原写入范围。缺行、父商品变化、范围漂移不能叫全范围生效。
- 当前授权身份前后核验；两次同商品 detail 的业务数据 hash 必须稳定。该检查不是服务端事务或 CAS 保证，无法消除外部操作员在检查间修改的风险。
- 另读 health-infos 的完整分页；原 SKU 分数缺失、父错配、坏 improvementList 或分页不完整保持未知，不缩小原范围。health 的短标题缺项只是 health 事实，不证明实际短标题值或正式审核通过。
- 通用 bossAuditStatus 不是已证实的正式短标题审核字段。正式短标题审核及门户来源目前未接通：`formalAuditVerified`、`portalVerified`、整体 `healthVerified`、`imported` 和 `retryAuthorized` 保持 false。该阶段不是完整 C3 或 merchant execute 上线。

## 原件与恢复

独立 observation/receipt/head 位于商家状态命名空间。原件绑定 import fingerprint、原 audit fingerprint、当时原 anchor 子集、当时完整 C2 prefix/receipt、全部原 SKU 的实际字段事实及 detail/identity/health 来源摘要。只存安全业务字段和 hash，不保存原 JSON/DOM/签名 URL/Cookie。

历史原件允许后续合法 C2/C3 观察增长，不能被当前结果替换；引用过的 anchor/C2 前缀缺失仍阻断。状态和 effects 分页明确是历史事实及 observedAt；只有当前 collect 返回 current-source 标志，不能借历史状态继续写入。

原件不完整时先核对。仅完整 observation 链可确定性恢复缺失 receipt、真正缺失的首个 head 或合法落后一条的 head。既存 null、bool、float、directory head，缺 observation、孤立/矛盾 hash、伪造派生 flags 均拒绝；不覆盖坏原件，也不重上传/重建任务。新 append 不允许倒退 C2 prefix。

每个证据文件的本地预算 64MiB，最多 10000 次观察；超预算明确保留原范围并停止，不截断、不把本地限制称为平台限制。更大范围的分段证据与真实类目/规模仍需验收。

## 仍需完成

正式审核/完整健康材料/门户原来源、确认失败行且当前确需修复的子计划及新批准、持续 owned worker 与 merchant execute 生命周期、完整 terminal 门禁和真实商家验收。C3 partial 不释放其他同店写入、更新或回滚。所有本轮验收是合成来源，未运行真实浏览器、jdo/OAuth/API、商家写入或付费模型。
