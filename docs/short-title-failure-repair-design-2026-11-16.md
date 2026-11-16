# 短标题确认失败修复设计（2026-11-16）

目标不变：商家安装一个仓库，Agent完成合法POP流程。失败修复不能复制原提交、用新根/新source抹掉未知结果，或自动继承原批准。本设计由实施负责人选择现有Python/原worker/原证据链架构；不是用户选择了新的技术平台。当前独立商家项目根与私有开发分支为既有执行位置，不新建其他聊天、工作区或修改内部版。

## 原父证据与本次需要

只有原C2全部批次完整终态且逐行结果确认failed才候选；pending/unknown/仅总数失败/缺原件均不候选。原B2、C2、C3证据始终保留，子计划精确绑定parentImportId/fingerprint、原audit/plan、原result sequence/receipt、原effect sequence/receipt和全部original sibling范围。历史读取可重建创建时事实，但不能声称本次需求已核验。

prepare必须在原owned browser同线程和实际install guard下前后核对当前整店上架目录、全部原兄弟库存范围，并实际collect_effects取完整v2健康列表/详情和实际短标题。原健康标题问题仍true、当前字段已实际观察、SKU仍在原上架范围且新文案不同于当前实际值才允许准备。新文案沿用原copy审核，并与全部未改变兄弟的实际短标题做NFKC/casefold去重；不从proposed值推断实际标题。没有完整已观察字段或原范围漂移时停止，不猜“缺了就该重投”。

## 子计划与批准

不可变repair-plan存于原parent目录，包含新changes及源proof，不复用原plan/import intent。按内容绑定一个业务intent；再次准备同一内容返回同一子计划，但仍重新读取本次源，不把一次读超时变成新计划。需要新的精确repair fingerprint/confirmed/TTL批准；原批准不能授权子计划。批准前再次真实核对候选仍failed、当前needs仍成立、当前原标题/范围/健康源语义一致。批准只是记录此子计划用户意图，不是已生成/已导入/retry授权。

本轮先实现准备、批准、分页/历史与原owner-worker命令。仍需本设计后续任务完成原native child导入、执行前重新核对、单次attempt/恢复、父子结果汇总与terminal：不将第一阶段局部实现冒称完整失败修复。

## 生命周期与安全

repair原件/批准纳入原worker native-prefix、同店与安装更新隔离；孤立、改写、删除、半写、错店、未知父根均拒绝，不覆盖坏原件。status/rows是严格只读历史。原readonly resume可准备修复但不能approve/execute；新批准需新的可批准生命周期，后续执行阶段再设计其原owner绑定，不能以新增命令绕过readonly。无真实OAuth/jdo/info/API/browser写入/付费模型/消息/公开release；所有业务验收合成。
