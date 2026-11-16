# 原确认失败短标题修复：准备及新批准

这是完整失败子导入的前置阶段，不能冒称自动重投已上线。当前 childImportExecutionAvailable=false、retryAuthorized=false、imported=false；native child上传/创建、执行恢复、父子结果/完整C3与更新释放仍待实现。商家只描述目标，以下命令由Agent运行。

## Agent步骤

1. 在原owned worker完成原results核对后，原C2全部批次须完整且逐行确认failed；pending/unknown/只见失败总数不能准备修复。仍使用原parent importId/fingerprint。
2. Agent整理已审核changes文件，每项恰为productId、skuId、shortTitle、review=passed。`short-title-worker-repair-plan --worker-id <workerId> --import-id <parentId> --fingerprint <parentFingerprint> --changes <file>` 在原owner实际guard下重新读取完整原库存/兄弟范围、实际标题、v2健康列表/逐SKU详情。只选原目标confirmed failed且当前hasShortTitle问题仍true、上架范围未变的行。
3. 新文案不能等于当前实际标题，并与全部未改变兄弟实际标题做NFKC/casefold去重。字段未观察、目录/身份漂移、来源缺失或冲突即停止。原成功/离线/未选中兄弟仍保留在历史siblings分页，不能变成子计划提交行。
4. 返回repairPlanId/repairFingerprint，原批准不继承。向商家说明精确修复范围并取得新明确批准后，Agent使用 `short-title-worker-repair-approve`，携带同样worker/parent标识、--repair-plan-id、--repair-fingerprint、--confirm；可设--ttl-seconds（30~3600，默认900）。批准前实际回读原任务当前完整C2逐行结果，再次读取当前need并核对原失败prefix/完整原标题语义没有漂移。
5. 两个命令均以原稳定requestId恢复接受/dispatch/独立回执；送达结果未知先short-title-worker-command-status查同ID，不换ID盲发。repair-plan默认按同请求内容生成稳定ID；需要新的只读观察时显式新requestId，但相同业务内容仍只对应同一个子计划intent。

## 历史、停止与限制

- `short-title-repair-status --import-id <parentId> --repair-plan-id <repairId>` 和 `short-title-repair-rows`（--view changes/siblings，--page/--page-size）仅严格读取历史原件；currentRepairNeedVerified=false，不能拿本地未过期approvalCurrentlyValid推断当前可写。
- 原readonly resume允许本地prepare/只读观察，不允许新repair-approve或execute。当前批准只在原仍可批准run中记录；关闭后的新可执行子生命周期为后续必须完成能力，不用新增命令绕过readonly。
- 子计划、业务intent、独立批准及其approval hash回执都在原parent目录；原C2/C3/worker native-prefix和关闭证据保留并保护它们。历史status/rows同时核对完整family、批准hash回执和已绑定worker前缀。丢index/plan/父根/批准回执、改写/孤立/半写、错店均隔离，不能用新计划替代原件。sourceData/原响应/签名URL不复制进入子计划或CLI输出。
- stop在当前读/写本地计划边界重新核对；批准只保存本次精确意图，不立即写店铺。正式审核/门户契约未核验，不从健康来源推断已审核或整体导入成功。本阶段不调用任何图片、视频、公司模型或付费生成。
