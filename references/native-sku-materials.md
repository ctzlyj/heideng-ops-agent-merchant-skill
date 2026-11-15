# 原生 SKU 信息分素材：审计与缺失槽位维护

此入口由 Agent 操作，商家只说目标。当前已完成**合成数据/独立安装验证**，未实测真实商家权限、素材受理、审核或京麦页面分值变化。接口字段依据当前官方 API830 目录和只读已验证参考契约；不是所有店铺/类目的兼容性保证。新媒体模型仍等待负责人确认。

## 实際支持

- 官方 `jdo-api-830` 的 GET `/rest/sp-product/v0/sku-materials`、POST `/rest/sp-product/v0/sku-materials/batch`。
- 白底图 white (31,1)、场景 scene1/scene2 (32,1/2)、卖点图 selling (33,1)、透明图 transparent (36,1)、文字 point1/2/3 (1002,1/2/3)。素材读取 scopeSet=1 图片、2 文字。
- 每个商品先用本店原商品详情 + 完整分页 SKU 列表交叉核对；分页必须提供稳定 total。最多1000个 SKU，每次最多50个 SKU。超出本地预算或结果不完整停止，不截断后声称全部完成。
- 查询该批 SKU 的全部上述类型及已存在 order，允许 API 返回顺序变化；漏 SKU、重复/外店 SKU、重复槽位、多图重复 index 或不明结构直接拒绝。
- **默认只填不存在的槽位**。已有槽位不自动覆盖。明确修复可使用 native-shop-material-repair.md 的v2原件合同：驳回或已通过但空槽、新文字/新图字节与URL、原审核状态均参与批准及执行校验；待审、未知和合格非空槽不覆盖。此版不提供删除/解绑或自动申诉。
- 图片必须来自同店原上传任务：任务已取得原始回执、上传字节 SHA 与图像解码证据一致、原 imgId/imgUrl 新鲜读回一致。首次肯定上传回执另行留存；被改写并重算摘要的任务回执不能替换它，旧 resolved readback 与原回执矛盾也拒绝。不能手填公网链接、把文件名相同当恢复证据、借用其他 Profile 或把 unknown 上传当已成功。
- 文字使用宿主策划/商家提供并内容复核的2–8字符短词组。`review=passed` 是宿主的复核标记，不是平台审核。原生业务约束仍由当前官方能力卡片和响应校验，无法证明的细节不猜。

当前实现会实际读取官方 cmd_info 使用的只读 open-metadata 能力卡片，将 apiName/method/path/输入 Schema 的摘要绑定进任务，并在写前重新核对。只支持经测试的有限 JSON Schema 子集；$ref、组合 Schema 或其他未适配声明会拒绝，不放行后猜字段。真实店铺卡片未获取，本次只用合成卡片；正式链路若返回不同结构，需证据驱动适配。

## Agent 执行顺序

1. 复用/连接用户明确的 merchant Profile；核对店名、venderId 和 POP 身份。开发授权不包含真实写入。
2. `sku-material-audit --profile <profile> --product-id <id> --include-health`。
   - `complete` 只表示本次商品 SKU/素材读取范围完整。
   - `scoreSourceComplete` 独立标记 health-infos 的分页完整性。
   - 官方将 health-infos 命名为“商品信息健康分”；healthScore / improvementList 可作为原生诊断证据。与京麦页面 commodity-score 是否逐行等价，**尚未实测**，不断言相同或不同。
   - 未读取/未出现/非可识别数值的分值不补0；在售范围从 SKU 状态独立核对。
3. 复核现有合法素材。图片先走 `material-upload-plan` 与独立上传批准、原回执回查；已有原上传任务直接复用，不重新上传。新图片/声音/视频模型未配置时说明缺项，不走员工通道。
4. Agent 在本地生成 changes 文件，仅放业务字段，无凭据。例如文字 `{skuId, slot, text, review}`，图片 `{skuId, slot, uploadTaskId, review}`。目标 SKU 必须属于该商品，SKU+槽位不重复。
5. `sku-material-plan --profile <profile> --product-id <id> --changes <file>`。保存整份计划指纹与每块任务，绑定原素材内容、来源、完整兄弟SKU集合及原上传证据。相同意图复用原计划，不新建付费/写入任务。
6. 向商家展示店铺、目标 SKU/缺失槽位、旧值和拟填内容、分块数、影响及限制。商家明确批准本次范围后，由 Agent 调用 `sku-material-approve --plan-id <id> --fingerprint <hash> --confirm`。一次范围批准，父计划单独留存授权并共用到期时刻。每块执行都检查父计划成员关系与规范化变更覆盖，单块 task-approve 不能替代父授权或延长父 deadline；不逐块续签或反复问。
7. `sku-material-execute --plan-id <id>` 串行执行。每块写前重新核对商品身份、完整 SKU 集合、原素材内容、上传来源、runtime/官方执行契约及最终授权时限；小请求也使用已审计官方同版源码 stdin，不能把最终 deadline 降成仅父进程检查。
8. `sku-material-status --plan-id <id> --refresh` 只读复查；不得拿 generate/invoke POST 查进度。

## 证据与恢复

- 原 POST 肯定业务响应 ≠ 每SKU已提交 ≠ 平台审核通过 ≠ 页面信息分提高。
- `materialFieldsVerified` 仅在**有原肯定回执**且全部目标内容及所有查询范围内未改槽位严格读回一致时为真。审核中仍可读回内容，但 `auditApproved=false`。
- `auditApproved` 只表示本次读回目标的原生状态全部为4；查询时间保留，不据历史值声明此刻或商品整体已审核。
- `scoreRecalculated` 始终false：不把内容读回当分值重算证据。
- 超时、响应含部分错误或无肯定业务回执：原任务 unknown，后续块停止。即使 desired state 已匹配，仍不证明未知请求作者/终态，也不解锁重提或其他写入。
- 已开始/已读回的块从不 POST 第二次；恢复重新核对原块。已受理但读回缺失、额外 order、其他类型被改或漂移则保留 submitted 并停止。
- 保证范围是查询的31/32/33/36/1002类型和该范围所有 order，**不是事务快照**，也不能证明未查询的未来类型未变。远端像素/素材合规性不由字段读回替代。

## 商家表达示例

> “先检查这款商品全部规格的信息分和素材缺口，已有待审和驳回图不要动；把真正缺的槽位整理成方案。”

> “这些图我已确认有权使用，先复核并上传；向我说明具体补哪些规格后，再按我批准的范围补齐，结果不明不要重提。”

上述自然语言会由宿主 Agent 编排，不要求商家输入命令或 JSON。该入口不假装已验证全店自动维护、短标题导入或电商视频上传绑定。
