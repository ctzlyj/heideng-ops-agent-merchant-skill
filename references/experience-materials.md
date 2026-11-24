# 商品内容、信息分与素材维护

## 适用问题与事实

已有 POP 商品短标题、图片槽位、白底/透明图、类目属性或驳回素材需要维护。先有正确店铺Profile、明确全店/单SPU/字段范围、当前SPU-SKU对应和真实缺口。以原冻结范围/平台响应为事实，不以主图观感推断全店信息分。

## 判断与可调整路径

- 通常先原 audit/plan-auto-maintain 确认缺口，优先使用已有合格素材；可与图文优化组合。商家已明确维护同一范围，按原流程批准一次，不再增加黑灯第二套审批。
- 短标题用原模板、SKU文本类型、冻结范围和 host agent-text-file。宿主实际生成后继续 `complete_short_title_import → import_short_titles`，不是交表让商家手工上传。独立文本 API 未配置不等于宿主不能写文案。
- 默认 agent 文本路线：原 auto-maintain 参数 `--text-model agent --agent-text-file <本任务真实生成文件>`；按原文件格式和冻结SKU生成，不能用假内容或随意扩大范围。可先只读/准备，不要求图片Key。
- 透明/白底沿用原平台批量抠图、可选本地cutout或原生成/修复；按驳回原因处理，不把抠图损坏与商品内容错误混成同一个问题。标准在线安装默认准备神经依赖和固定 SHA 的 Lite 权重；离线/未就绪时先看原平台路径并明确准备状态，不重写抠图工具。
- 生成确需新图时才准备商家LTS4AI Key、既定模型和本次费用范围；不继承原“公司多模型池”说明，更不回落公司渠道。

## 平台/工具边界与例外

原短标题导入工具保存了官方模板、加权长度16–30、单导入5000行、5MB等该版本契约；建议长度≤28属于经验建议。超限由原内部任务分批，不让商家拆表；平台当期规则变化要读当前契约，不能删校验。

只选原抽屉的文件控件；取得真实 createImportJob/任务ID，别把任务类型ID当任务ID。已受理不代表标题审核通过。失败明细明确后只补对应SKU；任务未知只读原任务，不重导整表。只有用户明确接受人工兜底才交可上传表；已自动导入的表标留档，避免重复提交。

## 工具与完成证据

- `run materials -- plan-auto-maintain|auto-maintain|repair-rejected ...`；`run short-title -- deliver-short-titles|validate-short-titles ...`；具体原参数从登记脚本读取。
- 短标题校验分别说明能否留档、能否直接作为一批提交。自动导入会保留原始工作簿，按每批最多 5,000 条和实际 XLSX 不超过 5 MiB 准备提交文件。只有平台失败明细中可核对、且已修正的行才进入一次返修，同样逐批提交。某批结果未知时先查原回执。商家无需手工拆表或重传整表。
- 自动导入来自 [pop_workflow](../mature/materials/scripts/pop_workflow.py)、[pop_browser](../mature/materials/scripts/pop_browser.py)，不是旧builtin。
- 完成证据分别是实际维护范围、上传/绑定响应、平台审核/health读回、短标题导入任务成功失败数。状态可能为 awaiting-review/unknown，不能一概报全部完成。

## 来源与适用限制

jd-material-pop-skill 2026.11.207 / b56b223；[导入说明](../mature/materials/references/short-title-import.md)、[浏览器导入](../mature/materials/references/short-title-browser-import.md)、[本地抠图](../mature/materials/references/local-cutout.md)。仅POP；员工自营/内部SDK流程不属于商家路径。宿主浏览器真实登录/导入、模型费用和平台写入没有本轮实测结论。


## 本轮实测卡点的处理（0.4.1）

- 单商品就是单商品：审计/计划用 `--target-spu-id`；已冻结整店计划允许选择同店已有 SPU 子集，但不能扩大原范围或覆盖另一任务状态。执行尾部的修复、属性和素材/标题回读沿用同一实际 SPU/SKU 集合。`--include-full-score` 不是扩大已冻结授权的许可。
- 低分用于选候选，不代表所有槽位都缺失。沿用原素材槽位查询，复用已通过图/卖点；审核中不重复提交，驳回走原修复/申诉。标题只补真实缺口，已合格标题忽略不改；宿主文本差集会报告计划外 IDs，重复 JSON 字段不再悄悄覆盖。
- **默认提示词可按任务重新设计**。Agent根据明确失败原因和真实参考图调整构图、表达，原范围/预算内直接继续。先核实文字来源：商品本体真实印刷误驳回走申诉；模型额外添加的文字可重设提示词重新生成。不要把默认模板当禁改规则，也不通过修改商品事实或原样重提解决问题。
- 生图前先做只读计划、宿主文案和本地环境/桥接预检；读店铺、盘点、标题无需图片 Key。已安装 3.12 解释器自动发现；特殊机器可由宿主设置 `HEIDENG_MERCHANT_PYTHON312` 为实际可用解释器路径，不做目录联接、不借个人/公司环境。
- 只有新图需要参考图。优先代表 SKU 的图，再官方产品主图/详情 `material.mainImages`、`skuList[].logo`；公共图片请求带浏览器 UA/商品 Referer，无 Cookie/Token。仍403或确实缺图时使用本商品用户给定参考图，不能绕权限、编图或误用别的 SKU。
- 自动短标题导入仍走原浏览器导入任务/拆分/失败行恢复。连接时让宿主在同店 owned `profileDir` 元数据里同时报告实际 `browserChannel`（chrome/msedge/chromium）；复用该类型，不把 Edge profile 丢给 Chrome，也不复制工作浏览器 Cookie。
- 属性沿用原类目模板、确定性规则、合法选项、提交回读。独立视觉未配置不再因图片 Key 存在而阻断盘点。宿主从真实规格/商品图/用户事实选值，写 `--agent-attrs-file`，JSON 为 `{产品ID:{evidence:事实依据,choices:[{title:属性名,n:[原模板选项索引],confidence:high}]}}`；计划可用 `--product-id` 限范围。无依据的材质/产地/认证不填，不用一个产地示例套全店。
- 同目标/费用已有批准继续执行，不再为免费抠图或同一费用逐项重复问；新增费用/范围仍说明。不能把已有素材复用的22秒当新图全流程预期。
- 大批结果打印摘要及 `resultFile`，完整结果放原任务 `.state`，宿主按需要读真实缺口/失败行，不把几十万字倒进聊天。查询对账须传包含 `批次*/.state/task.json` 的原任务根目录，错层路径明确报错，不返回空成功。
- 宿主回收进程后OS执行锁自动释放；旧执行标记只有确认原PID已退出才退休，不删除业务状态/未知回执。占位恢复不等于上传可重试。两次查无同名图片/槽位空不证明未知提交没有发生。


### 盘点费用口径与输入入口

`audit-pop-coverage`输出的generationEstimate区分SKU缺口、SPU和槽位估算，不等于实际付费请求数；同SPU图复用和人工接管保持。短标题宿主文案用agent-text-file JSON，`validate-short-titles`校验的是官方XLSX导入表，不能用JSON调用XLSX校验。模板沿用mature/materials/assets原文件。

## 0.4.5 现场反馈适配

- 主图、场景图和卖点图的正常生成主路径使用冻结计划中的同 SPU 受信商品图，不以“白底已审核”为前置。`No approved white source` 属于京麦批量抠图兜底分支，不得把它误讲成正常生图规则。
- 下载或覆盖的参考图在模型请求前归一化为 800×800 JPEG，减少非标准尺寸造成的拒付；不改变线上商品主图。主图含人物/道具而场景生成被拒时，先由宿主核对同 SPU 纯商品图，再在**原任务**用 `--reference-override SPUID=本地图片路径` 恢复；不得混用其它 SKU 事实；可以按本任务审核原因同时重新设计提示词，不让商家替Agent改。
- 常规新增透明图仍是本地快速派生，不等待白底审核、不调用付费模型。已有上传白底但透明图缺失时，恢复原同 SPU 白底并本地派生；驳回透明修复才走京麦优先、神经修复兜底，神经失败不静默退回旧泛洪。
- 用户明确“全店/全部维护”时，无冻结计划的只读规划应使用 `--include-full-score`；默认 0–89 分只是候选口径。audit 的槽位/issue 估算不等于最终付费请求或真实短标题缺口，以冻结计划的 SPU/SKU 差集为准，且不借该开关扩大已冻结范围。
- 单 SPU 恢复原全店任务时沿用原输出目录和 `--target-spu-id`，不要新建另一份底表任务。原任务目录内的全店文案经完整冻结计划校验后可直接投影到单 SPU；目录外输入仍严格校验当前子集，不静默过滤其它 SKU。
- `paused-unknown-write` 会给出原任务 `reconcile-receipts` 恢复命令。对账摘要有独立回执口径，不再把已回收结果显示成“0/0仍在处理”；未决项仍需逐项核对，平台 `material count mismatch` 不能伪报成功。

## 审计后的最小宿主交接契约（0.4.7代码候选）

1. 用原 `plan-auto-maintain` 盘点。返回 `hostHandoff.file` 指向同任务 `.state/host-handoff.json`；宿主读其中事实、待补SPU/SKU、输入schema和命令argv，不要让商家填写技术参数。无新费用时不弹Key。
2. 文案写进该交接指定的 `host-text.json`：`sellingPoints` 为SPU→三条卖点，`shortTitles` 为SKU→标题；仅补真实缺口。全任务文件仅经同店/目录/原源表SHA/冻结计划签名校验后可供单SPU恢复，不另写整表或换新目录。
3. 属性先执行交接的 `attributes.inventoryArgv`。依据原attr-plan里的属性和合法选项，按 `attributes.schema` 产出 evidence/choices/title/n/confidence=high；n是合法选项的0基索引，不是地区ID。按 replanArgv 重新盘点后，已有同范围批准才执行 applyArgv。无法可靠判断的产地/材质仍问商家，不猜。
4. 宿主规划与授权检查仍由宿主做；交接 `executionAuthorized=false` 不会自动扩大授权。executeArgv 是原成熟入口，用原目录/Profile，原摘要保存全回执于 resultFile。素材/标题/属性/修复分项有各自状态；局部完成不能称整项完成。
5. 返回命令已结束时不默认称处理中。`submitted`、`waiting-review`、`prepared`、`completed`、`needs-agent-action`、`needs-reconciliation` 分开；所有返回默认不建议重提。具体失败先由Agent处理；技术失败与未知核对使用 needsAgentAction；needsUserAction/needsMerchantAction 不因技术失败自动设为真。本人登录验证或新增费用/范围决策才提示商家。
6. 未知写入只使用原任务 recoverArgv/回执核对。完整性、店铺、范围校验仍保留；不能删除状态或伪造受理来跳过保护。

## 商家实战 g9jb 的执行纠偏（0.4.8代码适配）

- **先复用，后谈生成费用。** audit里的新估算按同SPU缺口并集与唯一approved来源区分：已有图绑定复用、真正新图、本地透明派生、来源歧义/审核中。imageGenerationRequestCount不再把透明图算作第五次付费，也不把SKU缺口当生图次数；estimateComplete=false时禁止拿数字报价，先读sourceIssues。历史snapshot缺来源可只读重盘，不删除原执行状态。
- 已确认全任务可直接用hostHandoff里的原目录/Profile执行一次，由成熟代码内部做批次/槽位；不要为每个SPU新建目录串行重跑全店盘点、修复和标题核验。必要试点后仍回到同一冻结任务。绑定仍用原京麦CLI/API，不另造网页写入调度。binding-submitted只说明该类型受理，binding-readback说明正在核对；不等于审核通过，不要用head截断活命令。
- **已有Key不是新费用授权。** 实际模型分支会从HEIDENG_MERCHANT_HOME的商家安全存储复用已记住Key；正常已批准生图无需因为入口差异再配置。没有Key时才走with_image_key.py安全输入，不显示解密值；同设备/同系统用户/同状态目录可复用，不能保证上游Key永不失效。
- **驳回修复默认免费。** repair-rejected默认等同--no-paid-generation，只执行京麦免费路径和申诉准备，返回remainingTargets/remainingImageSlotCount与已受理回执，不靠故意清Key抛异常收尾。auto-maintain默认--no-paid-repairs；仅当本次额外修复费用范围已批准，宿主才传--paid-repairs，或独立repair-rejected --paid-generation。原AUTO_MAINTAIN确认仍需保持，不增加商家层重复问卷。
- **商品本体字误驳回不是生图任务。** 白底/透明的“禁止出现文字信息”先由Agent看图确定来源，不能直接断言是商品本体文字。真实印刷误驳回走原productTextAppeals；模型额外文字允许重新设计本任务提示词修复，原样重复失败方案没有价值。不能把修复分支的缺Key错误推断成“240个白底都必须付费”；具体剩余以repair-scope和remainingTargets为准。申诉清单生成≠已提交申诉。
- 标题导入后单SPU平台回读已修正为同目标商品/SKU核验，不再与全店集合比较。工具结果仍须区分import-completed-awaiting-review和verified，不用上传数推断真实扣费或信息分已上涨。


## 0.4.9：保留原卖点、驳回范围与可读回查

- **不重写已有合格卖点。** 同店盘点取得的、同 SPU 唯一平台 approved 三条原值，带原来源快照原样复用，不因本地商业词表否决旧值；只是“已有”但未证明通过的草稿、冲突来源或新宿主文本仍走原校验。不得自造 `selling_points_origin` 来绕过新文本校验。1002 文本局部失败不阻断有效图片绑定；原未知/已提交的文本回执仍必须先核对。
- `audit` 默认只输出计数、估算完整性和 `resultFile/report`，完整槽位/来源问题留在原 JSON；确需全部字段时用 `audit --detail`。宿主直接解析该命令 JSON 或读取原文件，不做逐字符倒序切片找 `}`，不把 `tail/head/grep` 截断的数据当成完整结果。多店任务由宿主按原已连接身份逐店读取，不另造业务调度引擎。
- **付费维修显式限定类型。** 宿主根据商家已批准目标传可重复的 `--repair-kind white|transparent|scene1|scene2|selling`，只选实际 rejected 槽位；独立入口用 `--paid-generation`，auto 用 `--paid-repairs`。这些是宿主传参，不要求商家学习命令或重复批准同一范围。缺类型时返回 `repair-scope-required`，模型未调用。默认仍免费。
- 同原目录的 SKU 子集、`--exclude-spu-id`、`--exclude-binding`、类型过滤可单调缩小冻结范围，不能重新扩大。原共享请求/回执不改，恢复只读核对原请求，返回当前有效子集；未请求/未驳回的场景、卖点等不加入本次维修。
- 新付费图片前再次读当前槽位。approved/pending 直接保留，不生图、不重绑；缺失、URL 已改变或来源不唯一先核对；文字来源不明确时先由Agent看图判断。已知原修复回执覆盖的新驳回 URL 可按新任务提示词继续，未知回执仍不重提。上传后、绑定前仍保留原第二次槽位核对。原共享未知绑定先对账，不重发。
- 可用 `repair-rejected --max-model-requests N`，或 auto 的 `--max-repair-model-requests N` 限定**本次调用**剩余已批准图片请求额度（含质量重试与显式合法图片适配器）。N=0 不请求新图但可复用收到的响应/回执；未指定不代表无限费用授权。再次调用时由宿主依据原记录传剩余额度；它不是金额报价、总预算账本或终身上限。
- 每个付费维修响应保留同目录 `.request.json` 与收到的图片字节：received 按哈希复用；intent/unknown 或响应丢失不再次付费，不切换供应商猜重试。更换参考图也不能绕过同 SKU/同派生槽位的原未知请求；其它无关槽位仍按原范围处理。现有图片接口失败不保证没有扣费，缺少可查任务身份时须核对原服务记录，不能自动找回未知成品。已判定不合格的本地候选在有界质量重试前移除，避免中断后误上传。
- 输出分别报告候选修复素材组 `assetGroupCount`、失败组 `failedAssetGroupCount`、已提交回执覆盖的 SKU 槽位 `submittedSkuSlotCount`、当前槽位复用 `liveReusedSkuSlotCount`、本次模型请求尝试 `modelRequestAttemptCount`。已提交槽位包含原回执复用，不等于本次新增绑定数；模型尝试也不等于最终扣费。不能仅以不变的 totalCount 断言没有发模型请求，不能把“6 个待审 SKU 槽位 + 2 个失败组”说成“8 张图片”。
- 质量门禁原值 `cropped-edge/too-small/blurry` 会保留在完整结果，宿主据实际原因检查可靠 SKU 主图/参考图，不把笼统报错都称模糊。默认模板不限制任务级设计；明确失败后由Agent重新设计完整提示词，不机械重复旧方案。商品本体印刷误驳回走申诉，模型额外内容则可改提示词修复。


## 0.4.10：开放的任务级提示词设计

- 宿主负责设计，不另建黑灯规划引擎。默认只是起点；已批准目标/预算内，Agent读取实际驳回图和参考图，诊断原因，重设完整提示词并继续。修改提示词不要求商家另批一次；不扩大店铺/SPU/SKU/类型或费用。
- `generate`、`generate-auto-maintain`、`auto-maintain`、`repair-rejected` 可沿原命令加 `--image-prompts-file <本任务文件>`。hostHandoff 的 `imagePromptInput` 提供可选文件位置与接口；宿主自己写文件并构造 argv，不让商家填写。
- 文件按当前冻结 SPU 与图片类型映射。例如 `{"11":{"white":"针对裁切驳回重新设计：完整商品居中，充分留白，保留参考商品真实印刷，不新增标题贴片。","scene1":"新的完整场景构图提示词"}}`。提供的完整文本直接进入真实请求，不再附加旧默认 `_shared_image_rules`/repair hint；未提供的类型仍有成熟默认。可以给不同商品/类型不同设计，不影响已有合格图的复用。
- 只对本轮真正调用模型的图片生效。已通过/审核中的槽位仍直接复用；原京麦免费抠图不消耗提示词、不因文件存在自动变付费。需要模型白底路径时，宿主选择已有 `--model-cutout-images`/已批准的付费修复参数。transparent 提示词对应供抠图的中间商品图，不冒称接口直接输出合格 alpha。
- “禁止出现文字”不是商品印刷的证据。未知来源返回 `needs-image-review/imageReviewRequired`，先由Agent看图，不误称待平台审核或让商家手工修图。确认是模型额外文字时可用对象值：`{"prompt":"完整新设计","textOrigin":"generated","evidence":"已查看，额外标题在背景上而非商品印刷","rejectedImageUrl":"当前回读的驳回图片URL"}`；当前图片 URL 必须匹配后才进入该修复分支。真实商品文字用 product 表达看图判断，商品本身不被擦改。
- 新提示词形成独立修订素材组/响应记录，旧 received 字节、上传和绑定请求不覆盖。旧绑定 pending/unknown 先按原请求全量回读，不能缩小请求体或改提示词掩盖未知结果；已明确驳回的旧回执可作为同槽位来源证明继续新修订。当前 pending/approved 不生成；明确的模型拒绝是已知失败，旧请求不原样重提，新设计可用剩余预算；不把普通网络异常猜成已知拒绝。
- `imagePromptRevisions` 是输入版本信息，不等于本次已调用/已扣费。具体实际文本与修订留在原任务素材组的 `*-prompt.json`，结合模型 attempts、原绑定回执和平台审核状态判断结果。默认范本当前保留是为了稳定复用，不是禁止以后改进它。

## 全店维护和原任务回查

- 向商家报告 `coverage.inventory` 里的盘点对象数、实际查槽 SKU 数和各状态槽数，另报候选 SPU/SKU 数。属性只报该次属性回执覆盖的商品。旧冻结计划缺覆盖信息时先从已核店运行只读 `audit-pop-coverage`，有差异时保留原回执，用新目录重建计划。
- 同一 SPU 各 SKU 可以有不同的已通过图或文案。只补有缺口的 SKU 槽；待审保留，驳回按平台原因另修。遇到整批查询不完整或未识别状态，先回查事实。
- 产生新费用前，把 `feeQuote` 中的店铺、图型、新增张数、覆盖对象与计费条件告诉商家。同时执行已授权独立 workItems，短标题可在等待生图答复时用 `maintain-short-titles` 取得原回执。属性分支按单独范围取数。共享浏览器或同一个写入目标时顺序提交。
- 普通新素材和维修分别用原报价调用 `confirm-image-fee`。宿主把生成的回执传给 `--fee-approval-file` 或内嵌维修的 `--repair-fee-approval-file`。计价方式见[执行策略](execution-policy.md)。
- 新聊天先按本店两个官方身份字段查 `task-context`。独立修图任务提供 `originalScope`、原维修结果和只读 `check-repair-status` 命令。旧任务缺 Profile 时补入当前核验的本店 Profile。汇报上传、提交、待审、已生效与结果未知的单位及检查时间；未知项先查原回执。
