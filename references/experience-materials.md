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
