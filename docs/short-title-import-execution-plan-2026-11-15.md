# 短标题B2原生导入执行与恢复设计（2026-11-15）

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans、test-driven-development、verification-before-completion；最后一次独立有界审查。

**Goal:** 实现B2真正上传/创建实例的原生浏览器执行API及独立原件恢复，不让商家手工导表；B2不是完整B2/C/CLI-worker商家链路完成。
**Spec:** docs/short-title-import-design-2026-11-15.md。原完整库存、health和copy来自A1/A2；独立浏览器模板/同店原件来自B1。
**Architecture:** 只读且内容寻址的完整root计划，精确root批准；每批upload/create的独立attempt/业务ack/任务anchor先留账后派发；current task页精确file object/time/instance绑定，unknown只查原任务不重复上传/点击。实际执行使用当前商家公开商品页原抽屉，不猜REST写接口。
**Tech Stack:** Python标准库、既有BrowserRuntime/Playwright；合成factory，不依赖O2/员工profile/公司Key。

## Global Constraints

本轮仅合成店铺/身份/浏览器/响应/模板/批准；无真实jdo info/OAuth/商家网页/写入/任何付费模型/消息/公开发布。内部和个人Skill只读。Cookie/签名URL/原请求或响应正文不进入日志/JSON/源码/Git/回复；B2仅保留object/source/body哈希，私密URL只在原生浏览器当次内存使用，C结果文件后续从原实例重新查询。

## Review Focus

错店/离线/漏范围、换source重放同一未知intent、任一未来chunk文件/原件被改却提前写、批准/attempt/ack/anchor混淆、job类型ID冒实例、旧/错origin/不完整响应冒新业务接受、unknown重复提交或推进、仅提交冒生效、关闭/更新互斥被绕过。

### Task 1: 冻结root与独立原件状态
Files: short_title_import_state.py、short_title_imports.py、tests/test_short_title_imports.py。
Interfaces: ShortTitleImports(state,client,clock=None).prepare(planId,sourceId)/approve(importId,fingerprint,confirmed,ttl=900)/status(importId)/rows(importId,page,page_size,view)。root保存原plan/source指纹、同店、完整changes/chunks、每块原模板编译的文件/行hash、intentHash与runtimeVersion；status从独立原件重算，不读一个可改journal状态当权威。
- [ ] RED→GREEN：只有完整原source/template/copy，5000+1，全部未来文件核对；错shop/父/离线/ID/原件/hash/批准拦；同intent新source不能代替旧root；批准只精确root、不从开发授权推导店铺写许可。
Expected: 无浏览器upload/create；CLI准备/批准不是导入结果。

### Task 2: 原生浏览器派发与unknown恢复
Files: short_title_import_browser.py、short_title_import_contract.py、tests/short_title_import_fixtures.py；对B1加一个可核验source resume hook，B1默认依旧禁止重复capture。response hash明示浏览器body而非HTTP原线字节，完成body与压缩长度分开核对。
Interfaces: ShortTitleImportBrowser(manager,importId,factory=None,...).open/preflight/upload/create/observe/close；manager.execute(importId,browser)/recover(importId,browser)。只原抽屉唯一input、当前文件label和确定导入button；先保存attempt再动作。queryByPage只有已观察一页，不以缺少ID证明没提交。upload与create业务接受、source关联的实际instance、任务页anchor分开。
- [ ] RED→GREEN：真实class+合成UI动作、完整root一次批准逐块、upload/create超时/丢ack/伪jobId、明确非成功code不重试、不推进后块；有原task object/time可只读恢复，缺source或歧义保持unknown。
- [ ] 恢复约束：上传已确认但DOM/原native upload绑定丢失，不能重新set_input_files；仅原live DOM绑定还在才能首次create，否则保持待恢复，不能伪装已创建。create attempt存在永远只查原任务，不再点击。
Expected: 本地/安装mock真实调用set_input_files与create button；imported=false、原标题/health/逐行未核验，不称已生效。C验证和已确认失败行重试仍必须实现。

### Task 3: 命令接入、更新门禁和交付
Files: CLI的import prepare/approve/status/rows；short_title_import_gate.py；references/native-short-title-import.md；新安装smoke/全套/包/GitHub验收。
- [ ] CLI只是root准备/批准/历史分页；原生执行API可供同进程Agent调用，持久worker与商家CLI execute接入必须随后完成，不用假的execute入口冒上线。
- [ ] 任何原attempt、提交、unknown及孤立原件阻止更新/恢复/rollback；无attempt且完整prepared可以idle，但旧runtime未执行root不能自动写，跨版本安全重建另实现。
- [ ] 独立有界审查、主复现修复、同新包安装smoke与完整套件、脱敏审计、私有push及实际GitHub重装。
Expected: 只有B2 API范围完成；整体goal、C/worker、真实商家/类目/规模、生成来源及分发权利未完成。

## Pre-flight rulings

Task1→Task2：root scope全体文件都须先证明，不能只当前块；原批准与独立attempt不能互相替代。source同intent变更只能走原root，不重开未知写。
Task2→Task3：源响应hash只是浏览器正文证据，不冒称线长；真实merchant解码/schema另验。只观察task一页不能否证任务存在；恢复需当次instance+原上传object+原创建窗口（不从类型jobId/文件名猜）。已accepted但尚无anchor也是unknown，不推进。
上传接受后若原进程/DOM丢失，当前未发现合法native恢复upload-binding契约，不猜组件状态/REST，不重新上传；C/worker必须承接必要恢复能力。这不是export-only替代方案。
Shared install.lock继续由browser持有整个会话，root局部锁防重复动作，unknown时只是读而不是换工具派发。所有开发留在现有商家branch，不另建用户聊天/改内部Skill。

2026-11-16修正记录：原native JSON finished/解码body与wire长度分离，合成模板ZIP clock导致big scope模板hash漂移已定根，固定2000fixture日期，不放宽实际模板hash。新health审计原来二次争抢browser install.lock，改用真正持有的同线程/路径guard，并统一install-before-audit锁顺序；内联approve复用同一个活跃且核验open的browser guard，不通过CLI传任何skip-lock参数。当前被修复标题的原字段/逐行生效仍待C核实。

独立2 Important均主RED复现：contradictory/malformed实例字段与absent必须分开，原件保存instanceEvidence、矛盾始终停止自动anchor；actual ID在整个root去重且重算原件时再拒绝复用。root-wide首次自有fixture误在第1anchor前隐藏旧页，已明确修正为第1anchor存在后才隐藏；真正5000+1 RED已确认。主12窄方法GREEN，完整601+6及独立复核待完成，worker/C/真实商家/许可不是本轮API完成范围。
