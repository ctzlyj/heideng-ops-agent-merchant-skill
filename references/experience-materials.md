# 商品内容、信息分与素材维护

## 适用问题与事实

已有 POP 商品短标题、图片槽位、白底/透明图、类目属性或驳回素材需要维护。先有正确店铺Profile、明确全店/单SPU/字段范围、当前SPU-SKU对应和真实缺口。以原冻结范围/平台响应为事实，不以主图观感推断全店信息分。

## 判断与可调整路径

- 通常先原 audit/plan-auto-maintain 确认缺口，优先使用已有合格素材；可与图文优化组合。商家已明确维护同一范围，按原流程批准一次，不再增加黑灯第二套审批。
- 短标题用原模板、SKU文本类型、冻结范围和 host agent-text-file。宿主实际生成后继续 `complete_short_title_import → import_short_titles`，不是交表让商家手工上传。独立文本 API 未配置不等于宿主不能写文案。
- 默认 agent 文本路线：原 auto-maintain 参数 `--text-model agent --agent-text-file <本任务真实生成文件>`；按原文件格式和冻结SKU生成，不能用假内容或随意扩大范围。可先只读/准备，不要求图片Key。
- 透明/白底沿用原平台批量抠图、可选本地cutout或原生成/修复；按驳回原因处理，不把抠图损坏与商品内容错误混成同一个问题。没有可选神经依赖时先看原平台路径，不重写抠图工具。
- 生成确需新图时才准备商家LTS4AI Key、既定模型和本次费用范围；不继承原“公司多模型池”说明，更不回落公司渠道。

## 平台/工具边界与例外

原短标题导入工具保存了官方模板、加权长度16–30、单导入5000行、5MB等该版本契约；建议长度≤28属于经验建议。超限由原内部任务分批，不让商家拆表；平台当期规则变化要读当前契约，不能删校验。

只选原抽屉的文件控件；取得真实 createImportJob/任务ID，别把任务类型ID当任务ID。已受理不代表标题审核通过。失败明细明确后只补对应SKU；任务未知只读原任务，不重导整表。只有用户明确接受人工兜底才交可上传表；已自动导入的表标留档，避免重复提交。

## 工具与完成证据

- `run materials -- plan-auto-maintain|auto-maintain|repair-rejected ...`；`run short-title -- deliver-short-titles|validate-short-titles ...`；具体原参数从登记脚本读取。
- 自动导入来自 [pop_workflow](../mature/materials/scripts/pop_workflow.py)、[pop_browser](../mature/materials/scripts/pop_browser.py)，不是旧builtin。
- 完成证据分别是实际维护范围、上传/绑定响应、平台审核/health读回、短标题导入任务成功失败数。状态可能为 awaiting-review/unknown，不能一概报全部完成。

## 来源与适用限制

jd-material-pop-skill 2026.11.207 / b56b223；[导入说明](../mature/materials/references/short-title-import.md)、[浏览器导入](../mature/materials/references/short-title-browser-import.md)、[本地抠图](../mature/materials/references/local-cutout.md)。仅POP；员工自营/内部SDK流程不属于商家路径。宿主浏览器真实登录/导入、模型费用和平台写入没有本轮实测结论。


## 本轮实测卡点的处理（0.4.1）

- 单商品就是单商品：审计/计划用 `--target-spu-id`；已冻结整店计划允许选择同店已有 SPU 子集，但不能扩大原范围或覆盖另一任务状态。执行尾部的修复、属性和素材/标题回读沿用同一实际 SPU/SKU 集合。`--include-full-score` 不是扩大已冻结授权的许可。
- 低分用于选候选，不代表所有槽位都缺失。沿用原素材槽位查询，复用已通过图/卖点；审核中不重复提交，驳回走原修复/申诉。标题只补真实缺口，已合格标题忽略不改；宿主文本差集会报告计划外 IDs，重复 JSON 字段不再悄悄覆盖。
- **原生图提示词不改**。商品自身的字被误驳回，按京麦审核问题记原原因/关联槽位，走原申诉，必要时 `--exclude-binding SPUID:类型` 保留人工接管槽位。不擦字，不因这一原因反复付费生图，不把重新提交次数当解决证据。
- 生图前先做只读计划、宿主文案和本地环境/桥接预检；读店铺、盘点、标题无需图片 Key。已安装 3.12 解释器自动发现；特殊机器可由宿主设置 `HEIDENG_MERCHANT_PYTHON312` 为实际可用解释器路径，不做目录联接、不借个人/公司环境。
- 只有新图需要参考图。优先代表 SKU 的图，再官方产品主图/详情 `material.mainImages`、`skuList[].logo`；公共图片请求带浏览器 UA/商品 Referer，无 Cookie/Token。仍403或确实缺图时使用本商品用户给定参考图，不能绕权限、编图或误用别的 SKU。
- 自动短标题导入仍走原浏览器导入任务/拆分/失败行恢复。连接时让宿主在同店 owned `profileDir` 元数据里同时报告实际 `browserChannel`（chrome/msedge/chromium）；复用该类型，不把 Edge profile 丢给 Chrome，也不复制工作浏览器 Cookie。
- 属性沿用原类目模板、确定性规则、合法选项、提交回读。独立视觉未配置不再因图片 Key 存在而阻断盘点。宿主从真实规格/商品图/用户事实选值，写 `--agent-attrs-file`，JSON 为 `{产品ID:{evidence:事实依据,choices:[{title:属性名,n:[原模板选项索引],confidence:high}]}}`；计划可用 `--product-id` 限范围。无依据的材质/产地/认证不填，不用一个产地示例套全店。
- 同目标/费用已有批准继续执行，不再为免费抠图或同一费用逐项重复问；新增费用/范围仍说明。不能把已有素材复用的22秒当新图全流程预期。
- 大批结果打印摘要及 `resultFile`，完整结果放原任务 `.state`，宿主按需要读真实缺口/失败行，不把几十万字倒进聊天。查询对账须传包含 `批次*/.state/task.json` 的原任务根目录，错层路径明确报错，不返回空成功。
- 宿主回收进程后OS执行锁自动释放；旧执行标记只有确认原PID已退出才退休，不删除业务状态/未知回执。占位恢复不等于上传可重试。两次查无同名图片/槽位空不证明未知提交没有发生。


### 盘点费用口径与输入入口

`audit-pop-coverage`输出的generationEstimate区分SKU缺口、SPU和槽位估算，不等于实际付费请求数；同SPU图复用和人工接管保持。短标题宿主文案用agent-text-file JSON，`validate-short-titles`校验的是官方XLSX导入表，不能用JSON调用XLSX校验。模板沿用mature/materials/assets原文件。
