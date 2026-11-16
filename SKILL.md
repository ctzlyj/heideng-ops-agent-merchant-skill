---
name: heideng-ops-agent-merchant
description: Use when 京东POP商家希望安装黑灯运营智能体，或以自然语言处理店铺连接、商品上新复刻、信息分素材、主图详情、经营广告诊断、素材到手价采集、同规格比价和电商视频交接。不用于员工自营/招商/内网办公。
version: 0.1.1
---

# 黑灯运营智能体商家版

## 首次上手

商家不敲命令、不复制Cookie或授权码、不发送Key到聊天。所有命令由当前Agent用安装目录绝对路径执行。

1. 执行 python "<skill-root>/scripts/merchant.py" onboarding；用一两句话说明已就绪和当前确实需要的动作，不念整份清单。
2. 只有店铺功能需要CLI且未安装时，Agent执行 doctor --install-cli，从京麦官方公开源校验下载，不使用O2/内部SkillHub。
3. 问清当前目标和必要商品/店铺/报表。纯本地分析/采集/准备无需先授权店铺。已有明确目标店的授权只在实时核验后使用；新授权先遵守 references/shop-connection.md。商家只用京麦App扫码、完成平台本人确认；同一上下文衔接官方OAuth。
4. 生图服务已由用户选定：LTS4AI，base URL=https://api.lts4ai.com/v1，model=gpt-image-2.5。先读 references/lts4ai-image.md；当前adapter-ready，已复用MIT客户端接入文生图/参考图编辑/本地原图保存；image-plan→本次确切预算批准→image-execute，商家自有Key从安全进程环境读取。没有真实付费实测，但不以此无条件禁用调用。unknown查原记录不重投，不能虚构任务查询端点。视频服务仍awaiting-provider。不弹员工Key窗口、不读取旧模型Key、不静默切换付费平台。宿主自身的文本与识图能力可用于理解商品、策划及复核，不额外调用公司网关。

## 开放工具箱，不是目录白名单

先读 registry.json 或用 route 理解用户目标。目录外的合法POP需求也可自主查官方当前文档、组合宿主浏览器/文件工具、编写任务局部脚本。不要把“未登记”说成“不支持”；但缺授权、事实、平台接口或模型来源时要准确指出缺项，不凭名称猜接口，不回退员工系统。

以真实业务完成为目标，不只给建议：核对输入→读取来源→制定本次计划→在已有范围内执行→按官方回执和远端状态验收。不要把准备好的素材/计划/JSON/进程exit0当作上架/绑定成功。

## 可执行入口

- short-title-plan / short-title-status / short-title-rows / short-title-workbooks：先读 references/native-short-title-planning.md。完整原库存与health问题、宿主审核稿和模板编译的前置阶段，当前planning-only；不能把文件/稿称导入成功，不能给商家默认人工上传。该A入口不是导入执行入口；原生B2/C1-C2 API另外核对原件，持久 worker 入口见 references/native-short-title-worker.md，完整 C3 生效闭环仍待实现，不猜CLI写接口或用job类型ID冒充实例。

- ensure-shop / auth-start / auth-status / auth-observe / auth-cancel / auth-recover / auth-restart / auth-wait / auth-reconcile：独立店铺连接和同会话扫码OAuth。严格先读 references/shop-connection.md；只保存公开taskId，不导出私有授权页面；WorkBuddy等命令结束会清理子进程树的宿主使用auth-start --foreground --wait（安全重启也--wait），保持同一长命令直到终态；阶段变化JSON中userAction指引登录。失联不等于失败；auth-reconcile仅在原worker确认退出且未开始OAuth时标记可安全显式重启，原unknown只读恢复。当前Windows新授权已实现但真实商家链路尚未实测，macOS新授权因官方secret argv风险禁用。
- sku-material-shop-audit / sku-material-shop-status / sku-material-shop-rows：全店在售商品与全部兄弟SKU、原生信息健康分/素材的完整来源核对；分页摘要不会冒充全店，不以有分值的SKU当库存，未取得分值不补0。先读 references/native-shop-material-audit.md。
- shop-material-plan / shop-material-approve / shop-material-execute / shop-material-status / shop-material-rows：原完整审计上的整店可用素材统一范围、逐商品50SKU分块与原件恢复。默认覆盖全部已支持槽位、缺模型只报告等待素材不静默缩范围；未知不重提/不推进，根批准不能被子批准替代。先读 references/native-shop-material-execution.md；明确驳回/空槽修复再读 references/native-shop-material-repair.md，旧状态/理由和原图字节留证，新图不能换URL复用旧字节；部分成功≠整店信息分维护完成，真实商家链路未实测。
- sku-material-audit / sku-material-plan / sku-material-approve / sku-material-execute / sku-material-status：本店完整 SKU 和原生素材缺口审计、原上传回执或宿主审核文字的缺失槽位绑定；先读 references/native-sku-materials.md。批准整个明确计划一次，各块单独留账；unknown、内容漂移和待审/驳回旧槽位不自动重提。
- product-list / sku-list / health-list / product-detail / price-plan / price-status：实时原生商品、完整SKU、健康分和受控京东价更新。改价前先读 references/native-products.md，绑定旧价/类目与两阶段验证；待审匹配不是线上生效，unknown不换Profile或接着执行另一写任务。
- diagnose：用户CSV/JSON/XLSX经营广告资料的定量诊断，缺指标标记partial/unavailable，不造黄金眼/EasyBI数据。
- compare：有逐SKU原生上下文价格证据和结构化规格的同规格TOP10。不能把京东价与到手价混用，不依照片就猜规格。
- material-audit：保留所有SKU，按199个SPU拆批，列缺口；优先复用用户已有合规素材，新增图片使用已接入LTS4AI客户端，商家Key及本次预算批准后执行，不调用公司模型。
- prepare-listing：真实实拍、用户卖点、真实类目和全部规格→独立listing-package；保留所有SKU，不为未上架产品造京东链接。
- package-snapshot：把宿主在商品原生上下文实际采集的SKU顺序、每SKU到手价和素材整理为包。采集前读 references/collection.md；不把静态搜索价当真实到手价。
- attach-video：用户已有视频/封面进入manifest；独立全帧/音轨解码、真实封面、视频/封面/商品上下文hash及实际视觉/试听确认齐全才bindable；技术检查不由布尔标志替代。上传前video-preflight复核。见references/local-video-handoff.md；本地就绪≠原生上传/绑定已完成；原生已有视频上传/保存使用video-delivery-plan/approve/execute/status/cancel批准会话，见references/native-video-delivery.md。SKU绑定使用video-binding-preview/plan/approve/execute/status独立批准，见references/native-video-binding.md；当前仅经离线/合成验证，真实平台未实测，不调用生成模型。
- official-doc：按官方版本策略SHA读取指定协议。先审阅接口字段/语义；能力新变更时查官方当前metadata，不套旧版参数。
- task-plan / task-approve / task-execute / task-status / task-readback：业务操作的身份、范围、写入授权、去重、unknown与回查。官方CLI调用必须显式非default Profile、vender身份和目标店名/venderId一致。

完整用法见 references/commands.md、references/workflows.md。

## 店铺写入与费用

用户要求设计/安装/诊断并不自动批准上架、改价、绑定、消息或媒体付费。用户明确批准了具体范围时，Agent仅记录一次相同范围批准，不反复提问；变更店铺、商品、模型、数量或预算是新范围。

真实写入必须先形成task-plan并展示目标店、商品、操作和变更内容，获得对应用户批准后task-approve，再task-execute。submitted不是生效；用官方读取或已授权页面核验task-readback。unknown不得重提、换工具重提或删除状态，先查原回执和远端。不能直接绕到原CLI或浏览器执行未批准的写入。

## 不可越过的隔离

只用商家本人合法权限；禁止员工ERP/SSO、黄金眼代理、EasyBI、JoySpace/京ME、公司模型、oxygen-h3和集团账号。内部安装副本、配置、凭据、更新任务和店铺数据不能改动。清单以外任务同样适用。

Key/Token/Cookie/授权码/设备凭据不进聊天、argv、源码、日志、截图或Git。不要读内部Key，即使存在。不要使用原视频11190/jd-main-video-batch；视频工作流源码仓库固定ctzlyj/jd-pop-main-video-skill；生成模型服务来源另待确认，由merchant包装读取经审核版本，不安装未经处理的上游SKILL。

## 安装与更新

入口 install.py；官方依赖由Agent按需要自动补齐，商家不用另找仓库。启动时或显式做更新发现，候选下载/SHA/兼容检查通过且无进行中/unknown任务、无用户修改才切换；失败恢复，禁止静默降级。后台不扫码、不弹窗、不建未经请求的定时任务。原生视频与绑定独立证据也纳入空闲门禁；unknown/丢失证据时恢复清理、安装和回滚都不得进行。新视频计划冻结运行时版本；只有明确取消且无业务尝试的本地计划可保留取消证明后重新规划，不能取消unknown。详见 references/native-video-delivery.md。

每轮简报已完成、真实证据、未验证部分、输出绝对路径；媒体生成、官方授权、店铺线上生效分别描述，不能编造。


大图片/大上新JSON使用本仓库官方版本绑定stdin薄适配，见references/official-transport.md。task-plan的officialExecution必须展示与绑定；0.3.7公开源为deprecated，不能隐藏或当成正式新SDK。只在提交前选择transport，不因未知结果换方式重提；源码和载荷不得放OS argv或落源码日志。


已有图片的原生素材入口见references/native-materials.md：先查询本店空间/分类，按原bytes SHA规划、批准、上传，再原imgId回查。批量保留全部SKU/文件映射，图片保存与商品主图/详情绑定分开；unknown不靠名称搜索解除。当前模型来源等待补充不阻塞已有合规图的本地解码和素材流程。

## 完整编辑模板前置能力
已有商品先用product-schema读取并保存完整原生模板与SKU分页证据；schema-image-draft仅改原imageTargets中已有图片槽位，所有SKU/详情/非目标字段不变。素材来自同Profile的原已知上传回执fresh回查。SkuUUid不当真实skuId，色图mappingId不猜造，主图/逐SKU图/详情不混为一个“成功”。详见references/native-product-schema.md。当前draft明确submissionReady=false，不创建可执行商品提交任务；不能对商家宣称已完成整版发布或绑定。

## 全SKU新品原生流水线
新品不只出listing-package：先publish-categories/publish-brands/publish-context取本商真实许可与规则；按公开官方组件/销售属性指南填完整schema和来源，不猜ID、不删SKU。publish-validation-plan生成精确校验范围，批准后execute；已知成功才publish-plan生成同body的提交范围，再绑定明确用户许可。所有原照片、全部价格/库存/规格和源商品进入前检；共享task-plan不能绕过，换校验nonce不能重复创建。publish-status只读原回执、不制造新链接，不把受理当线上已生效。详见references/native-publishing.md；新品不代替现有商品整版编辑/图片绑定与视频上传。

既有商品整版图片/详情编辑：按 `references/native-full-edit.md` 先保留全原详情/组件/SKU并建立逐字段来源基线，运行 schema-edit-baseline/schema-edit-validation-plan/schema-edit-plan，再分别精确批准。原 applyId 的完整字段回查和原 productId/全 SKU 回查分开；不把模板/受理/当前目标值匹配当作原 unknown 请求终态。缺字段声明/完整模板时查明，不猜默认值、不借内部接口。

### 原生规则模板自动准备
既有商品图片/详情目标先走 product-schema，再 schema-edit-prepare --capture-id；必要时 schema-compile 查看自动编译与原 capture 证明。详见 references/native-template-compile.md。由 Agent 运行，不让商家手写全 SKU schema、bindings 或 sale-sources。没有声明/协议证明时读取当前官方原生文档及合法实际模板查明，不以相等值、默认值或删未知字段伪装 ready。仍通过原 validation/正式提交批准与原申请单/全字段回查；重复 prepare 不新增正式意图。

health-list 读取官方命名的“商品信息健康分”及 improvementList；与京麦页面 commodity-score 的等价性未实测，不断言相同或不同。素材空间保存、SKU 专属绑定、平台审核和分数重算不能互相替代。原生缺失槽位审计/绑定先读 references/native-sku-materials.md。

- short-title-import-plan / short-title-import-approve / short-title-import-status / short-title-import-rows：先读 references/native-short-title-import.md；原生execute/recover API会真实写入，必须本次精确root批准。CLI 持久 worker 已接入，先读 references/native-short-title-worker.md；启动只读、精确批准后原进程执行，当前仍不能称完整标题生效；unknown只查原件不重传、不推进。C1/C2 collect_results只读获取原实例结果、完整逐行处理回执，状态/--view results可分页；先读 references/native-short-title-results.md，rowResultsVerified不是实际title/audit/health通过或retry许可。

原范围实际短标题/health 回读与持久化证据已接入部分原生来源 API；持久 worker 已接入；完整正式审核/门户/health 与确认失败子导入执行仍待完成，不称整店生效。Agent 用法与历史 effects 分页见 `references/native-short-title-effects.md`。

C3 v2 native 健康列表/逐SKU详情的独立前后观察已接入原 worker effects；先读 `references/native-short-title-health.md`。这是健康来源与特定标题问题的证据，不是正式短标题审核、门户或整店导入完成，不放开未知/重试门禁。

原确认失败修复准备/新精确批准已接入原owner worker，先读 `references/native-short-title-repair.md`。repair-plan仅选原完整C2确认失败且实际current need；repair-approve重新核对来源，不继承原批准；历史status/rows不等于当前可写。childImportExecutionAvailable/retryAuthorized/imported仍false，完整native子导入与恢复必须继续实现，不以此准备阶段冒称自动修复上线。
