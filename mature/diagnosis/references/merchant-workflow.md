# 成熟商家经营/广告诊断工作法（选择性复用原 SKILL）

来源 `ctzlyj/jd-store-diagnosis-skill` 0.2.0 / `42971c041248bab27f4d627357dcc475f848eb75`。
以下是原业务硬约束、商智/京准通采集、分析和已知接口条件，保留历史验证归属，不能当作本次商家适配真实验收。
宿主启动/登录由本包成熟连接器和实际任务浏览器工具承担；不复制原按进程/目录强制结束 Chrome 的 Windows 启动路径，不猜9224，不复制个人 Cookie。
原文指标中的黄金眼注记只作为历史差异说明，商家禁止调用员工黄金眼/EasyBI/cxjzt 回退；缺项按原数据说明报告。本地 Markdown + Excel 为交付，不发布或通知。
商家命令由父调度 `run --entry scripts/<原已登记脚本> diagnosis -- <原参数>` 执行；运行目录及文件路径由 Agent 生成，不让商家敲命令。

## 硬约束（每次都必须遵守）

1. **绝不抢占用户工作界面**：所有页面操作用后台标签（createTab 第三参 background=true），标签用完关闭；启动 zguard 循环守卫把店铺浏览器窗口压到底层；绝不切换/导航用户正在用的浏览器
   - **例外=店铺浏览器窗口接管（仅限用户明确授权过的店铺 profile，2026-09-29 用户授权云擎四店+圣迪欧）**：定时采集或处理这些店铺的任务时，遇到店铺浏览器窗口开着，先**优雅关闭可见窗口**（WM_CLOSE，15 秒未退再强制）→ 拉起 headless 执行 → 任务结束**按原启动页重新打开**（多标签无法精确恢复，Ctrl+Shift+T 可找回）。只动已授权店铺 profile 的窗口；未授权店铺、用户个人浏览器仍然绝不触碰
2. **凭证不落盘**：Cookie/Token 不进源码、日志、报告、截图、Git；请求头在内存中生成/捕获使用（sz-fetch.js 已如此实现）
4. **可回溯**：config、计划、原始数据留在任务 work/ 目录，报告中的每个数字都能回查
5. **投放产品线红线**：行动建议不推荐京准通「全站推广」产品线（即 fullMarketingScenarioTypeName = 「商品-全店商品推广」的托管计划）；全店/全站类托管统一要求走快车体系——快车-全店 优先积累访客、快车全站智能扩量。诊断中发现店铺存在京准通全站推广类计划（如「全店推广计划」）时，处置方向是收缩/迁移到快车，不是加该计划的预算或目标 ROI
6. **口径与交付闸门**：报告口径以 `references/metric-dictionary.md` 为准；派生指标一律脚本计算，不心算；交付前跑 `python -X utf8 scripts/validate_report.py --md <md> --xlsx <xlsx> --shop-id <id> --shop-name <name> --full`，0 FAIL 才发布，闸门输出随交付说明给出

## 流程（六步）

**先跑 L1 官方巡检（免浏览器，所有店可跑）**——完整口径见 `references/inspection.md`：

```powershell
# 核对店铺身份（返回 shopId/venderId/店名，与用户指定或已核验记录比对，不匹配立即停止）
node scripts/cli.cjs identity --profile "<已授权Profile>"

# 首次/CLI 升级后：先验证 1 个商品，再 10 个；抽样不能包装成全店完成
node scripts/cli.cjs scan --profile "<Profile>" --shop-id "<shopId>" --shop-name "<完整店名>" --scope sample --limit 1
node scripts/cli.cjs scan --profile "<Profile>" --shop-id "<shopId>" --shop-name "<完整店名>" --scope sample --limit 10

# 用户确认全店范围后：
node scripts/cli.cjs scan --profile "<Profile>" --shop-id "<shopId>" --shop-name "<完整店名>" --scope full

# 次日复检（对比前次报告，输出 新增/持续/已恢复/无法判定）：
node scripts/cli.cjs scan --profile "<Profile>" --shop-id "<shopId>" --shop-name "<完整店名>" --scope full --baseline "<前一次 report.json>"
```

- 只读：固定官方 GET 白名单，无任务队列、无平台写入、无自动登录；取数节奏 300ms/请求，AUTH/RATE/连续失败自动停
- 报告默认存用户目录 `.jd-store-diagnosis/runs/<运行目录>/`（report.md + report.json），每次新目录不覆盖
- 行动清单按 `references/inspection.md` 的路由表写明建议承接 Skill；素材缺口→jd-material-pop、主图批量重制→jd-jingmai-batch-image-refresh、比价→jd-competitor-price-adjustment-skill 等
- 采销只读巡检结果时，问题清单里「数据不足」的项不编造结论，与 L2 交叉补齐

### 2. 生成采集计划

复制 `scripts/diagnosis-config.example.json` 为任务目录下 `diagnosis-config.json`，填：诊断/对比日期、pin_id（京准通账户号）、cid2（商智行业类目）、cid3（京准通行业类目）、top_sku_ids（先跑第 4 步的 ind-kw-sku 再补填）。

```powershell
python scripts/make_plans.py --config diagnosis-config.json --out work/plans
```

产出 4 个计划：plan-sz.json（商智）、plan-jzt-report.json（账户/计划/分日）、plan-jzt-dims.json（报表 8 维度×当月+对比月）、plan-jzt-industry.json（行业大盘/榜单/推荐词）。

### 3. 采集商智（sz-fetch.js）

```powershell
node scripts/sz-fetch.js --plan work/plans/plan-sz.json --out work/sz --page https://jdsz.jd.com/szweb/view/index/home.html
```

- **签名（2026-09-15 起 szweb 强制）**：每请求算 `User-mnp = md5(pathname + uuid + 毫秒时间戳 + 固定盐)`，sz-fetch.js 已内置自动计算，直接用即可；若平台再改签名，回到页面里抓真实请求头对照排查
- 校验：gateway `header.code == 0`。响应在 `body.data`；size=0 表示无权限或参数错，对照 references/api-reference.md 修
- **响应 shape 差异**：多数端点 `body.data` 是 list；搜索词榜 `body` 本身就是 list；商品明细表（productTable）首行是 `$summary: true` 的合计行，统计明细前先过滤
- 建议加采三块（端点见 api-reference.md）：首页「商品诊断/流量诊断」（getProductAnalysisData / getFlowAnalysisData，官方预警口径）、「今日快照」（indexSummary/summary，实时口径仅看方向）
- 流量来源（flowSource）只有 APP 渠道口径，没有站外/PC 合并行，报告数据说明要写清这个限制

### 4. 采集京准通（jzt-run.js）

```powershell
node scripts/jzt-run.js --plan work/plans/plan-jzt-report.json --out work/jzt --nav https://jzt.jd.com/report/index.html#/rtb/basic
node scripts/jzt-run.js --plan work/plans/plan-jzt-dims.json --out work/jzt-dims --nav https://jzt.jd.com/report/index.html#/rtb/basic
node scripts/jzt-run.js --plan work/plans/plan-jzt-industry.json --out work/jzt-ind --nav https://jzt.jd.com/custom-report/#/industry/market
```

- 校验：`code == 1` 即成功。**响应 shape 有三种**：账户报表数据在 `data.datas`；行业 whole/billboard/area 数据在 `data.rows`（月度汇总在 `data.summariesMap.TOTAL_SUMMARY`）；热搜词榜/品牌榜 `data` 本身是 list。脚本日志 rows=0 有误导，先看 code 再解析 body
- **账户余额必查（断投风险）**：`POST https://atoms-api.jd.com/financecore/subaccount/allbalance/get`（body `{}`，页面上下文内 XHR）。cashBalance 为 0 或接近 0 → 广告可能已断投，必须进「立即做」行动项——断投不只是丢当天订单，智能计划的模型学习也会被打断

### 4b. 实时订单查询（当日数据，归因/核验专用）

商智是 T+1/快照口径、京准通报表是点击归因延迟口径——回答「**今天/刚才发生了什么**」（当日成交归因、稳赚 cap 当日变动归因、活动实时效果核验、商家口头反馈对不上报表）时，必须用京麦订单列表的实时接口，禁止拿商智快照当实时证据下结论。

**第一优先：京麦 CLI 官方接口 `jdo-order-manage`（订单管理，读+写，2026-10-08 用户提供）**：

| 场景 | API |
| --- | --- |
| 订单列表查询（按状态/时间分页，返回字段可自选） | `GET.sp-order.v0.orders` |
| 修改商家备注及旗标颜色 | `PUT.sp-order.v0.orders._orderId.vender-remarks` |
| 修改收货人/电话/地址（仅 SOP 等待出库状态） | `PUT.sp-order.v0.orders._orderId.consignees` |
| 按 SKU 分组拆成子单 | `POST.sp-order.v0.orders._orderId.child-orders` |

列表查询返回很全：订单状态、SKU 明细、支付信息（含 `actualPayAmount`=实付、`shouldPayAmount`）、收货人、配送方式、发票、买家/商家备注、售后单等。诊断/归因场景只用读接口（GET.sp-order.v0.orders），写接口不在本 Skill 范围。

**已实测可用（2026-10-08，云擎云仓/Ai/生活三店）**，调用模板与踩坑：
```powershell
jdo-cli invoke --url /rest/sp-order/v0/orders --method GET --profile <profile名> --params '<JSON>'
# params 必填项缺一不可（逐个报错提示）：page、pageSize(≤100)、sortBy(createdTime|modifiedTime)、sortOrder(ASC|DESC)、orderStatus(ALL)
# 可选：startTime/endTime(毫秒，按 sortBy 字段检索，窗口≤1个月)、scopeSet=["paymentInfo","skuItemInfoList","orderFlag"]
# 返回：orderId/createdTime/orderStatusDesc/paymentInfo.actualPayAmount(实付)/skuItemInfoList(含SKU名、促销明细)/orderFlag
# 焕新补贴订单在 orderExt.govSubsidyInfo 带「下单立减」标记，可识别补贴单
```
- profile 对应店铺（本机 `~/.jdo-cli/profiles/`）；若报 10201001005「页码小于1或者太大」，是调用方漏传了 `page` 必填参数，**不是权限问题**，补上 `page` 后重试即可（2026-10-08 吖嘟咪实测：漏传 page 报此错，补传后正常返回）。若真返回 403「无权限调用」，先核对是不是用了子账号 profile，主账号 profile 通常有全店权限
- actualPayAmount 可用于真实盈亏核算（实付/消耗），与报表京东价口径互为补充

```powershell
node scripts/probe-orders.js <cdp端口> <输出目录>   # 默认订单列表页 allOrders
```

- 原理：后台标签打开 `shop.jd.com/jdm/trade/orders/order-list?tabType=allOrders`，截获页面自己的 `dsm.order.bff.orderListBffService.queryOrderPage` 响应（结构化、50 条/页、最新在前）
- 解析要点：`body.body`（JSON 字符串）→ `data.results[]`：`orderCreateTime/paymentConfirmTime/orderCompleteTime`（毫秒时间戳）、`orderItems[].skuId/jdPrice/num`、`orderStatusInfo.orderStatusName`（已完成/已取消/已出库）
- 已验证场景（2026-09-28，稳赚 cap 归因）：商智显示「09-23 以来仅 1 件 41.82」，实时订单页实为「当日 21 笔 51.8–70.8 元」——T+1 快照把归因引向完全错误的方向
- 只读探测；订单含买家个人信息，原始响应仅留在任务 work/ 目录，不进报告/Git/日志
- **风控降级路径（2026-10-03 验证；2026-10-08 更新层级）**：shop.jd.com queryOrderPage 若返回 code=601 风控（提示「明天尝试正常浏览」），**不要反复重试刷接口**——降级顺序：①京麦 CLI `jdo-order-manage` `GET.sp-order.v0.orders`（首选，先做小样本实测）；②商智订单明细页 `jdsz.jd.com/szweb/view/tradeAnalysis/orderDetails.html`：页面自有接口 `szgateway.jd.com/api/lowcode/orderDetails/getDealOrders.ajax` **不受该风控影响**，页面内点「近7天/近30天」即可截获结构化成交明细（字段：`ItmId`=SPU、`OrdAmt`=订单金额、`SkuJdPrc`=京东价、`Time`=日期、`PayTm`=支付时间；成交/取消/售后三个页签）——T+1 口径，回溯近几日成交、终判类问题直接够用，当日归因以 CLI 为准。参考实现：`京麦广告诊断` 工作区 `work/_probe_sz_orders3.js`（页面点击+截获响应）。

### 4c. 普惠到手价查询（广告定价口径，投放/调价前必查）

**ROI、广告出价、点击成本的定价依据一律用「普惠到手价」，禁止用京东价。** 京东价只是展示价（例：云仓主投 SKU 京东价 60.8、到手 43.86，按京东价定价会把承受力高估 1.4 倍）；系统建议出价/推荐 ROI 是平台口径，不能直接抄。到手价随促销活动变动，每次开计划、调价、做投放方案前实时查询。

```powershell
node scripts/probe-arrival-price.js <cdp端口> <输出目录>   # 输出 all-skus.json（全店分页拉全）
```

- 原理：后台标签打开 `shop.jd.com/jdm/mkt/market/market-risk`（京麦 → 营销 → 促销工具 → 营销价格管理），页面上下文内 fetch `dsm.market.tool.common.api.PriceQueryOuterService.queryPriceInfoList`（`params` 支持 `pageIndex/pageSize/spuIds/skuIds` 过滤；无需 h5st，2026-09-29 实测 status 200）
- 关键字段：`perfectArrivalPrice`=普惠到手价（真实回款口径）、`jdPrice`=京东价、`minPrice`=理论最低价、`skuName/attrValueAlias`=规格；`wareId`=SPU
- 出价公式（用户确认）：**出价 ≤ 到手价 × 20% × 该词CVR**（单均广告成本 = 出价÷CVR ≤ 到手价×20%）；20% 低于已确认毛利 34.5%（云仓），留安全垫。低于 0.8 元起投下限的词删，不硬投；**京准通关键词计划系统最低日预算 50，不要再给低于 50 的预算建议**（2026-09-29 用户红线，原低于 50 的计划已全部提到 50）
- 关键词计划配套纪律（2026-09-29 四店实战定型）：控点击成本(CPC) + 切词匹配 + 否定词兜底；单均成本超线不加价；礼物类高价词全删；方案与报告中的关键词预算一律 ≥50，勿自相矛盾
- 只读探测，不创建/修改任何促销

### 5. 分析（结论导向）

怎么组织、怎么措辞由你自由发挥，但产出必须满足：

- **结论先行 + 行动清单紧跟其后**：老板 3 分钟内能消化「发生了什么、要做什么」；动作按 A 立即（24小时内）/ B 本周 / C 本月编号，具体到可执行（给计划编号、给词、给出价、给金额），禁止「建议优化」这类空话；每条动作在后面明细里有数字依据可查
- 每个结论有数字证据（环比/对比期/同行/行业），归因到「能动手的杠杆」
- 计划处置四类：加投（ROI≥2 且花费≥100）/ 保持微调 / 降价收缩（ROI<1 且花费≥300）/ 关停（零订单且花费≥20）
- 报表 8 维度 0 行 = 全智能托管黑盒 → 必给「开手动快车」行动项；词单 = 商智搜索词高转化词 × 京准通行业榜单/推荐词，出价用行业参考价上下浮 10%
- 冷启阶段店铺（新店或全店访客 <300）的广告行动项按 `references/ad-cold-start.md` 执行：快车-全店 优先走「积累访客 → 全站智能扩量 → 稳赚计划」优先级、访客<300 不强行加量、按 CTR×CVR 四象限处置；判断前先确认店铺所处阶段，不套成熟店加量逻辑
- 行业对照双口径：商智（成交）+ 京准通（广告），分两小节
- 商智/京准通广告数据交叉核对（如全店推广计划花费两边应一致；ROI 差异是归因窗口不同，要在数据说明里解释）
- **广告消耗区分「红包/虚拟金」与「现金」两种口径**：新店红包、稳赚赔付红包都是虚拟金且限指定推广场景（30 天有效期）；报表消耗数字常把两者混在一起，把红包消耗当现金会把「红包低效」误判成「现金亏损」（2026-09 四店横评：总消耗 808 元里约 800 元是新店红包、现金仅约 8 元，带回 527 元成交——正确结论是红包低效，不是现金亏损）。写报告前先核对京准通财务账户-红包明细，消耗、ROI 与「是否亏钱」结论均按红包/现金分别表述
- 异常数据（单日异常、断投日、高基数失真）坦诚说明，不假装没看见
- **派生指标零手算**：环比、占比、ROI、CPA、客单价、UV价值、月化一律脚本计算；报告与 Excel 同源，同一指标只有一个数
- **行动项带量化目标和时限**：每条动作写清「做到什么数、什么时候验收」（如「11月客单价≥¥155」「两周后快车ROI≥4.4」），证据与动作一一对应
- **数据缺口逐项声明**：缺哪个维度、为什么缺、影响哪个结论；不删板块、不编数，取不到的板块保留并写「数据不足」
- **不完全月/大促脉冲**：部分月统一同期天数或日均，不与整月直接比；大促日、异常日单列，不混进日均结论
- **货端质量（数据可得时补）**：信息分、价格星级、店铺星级、好评率（剔除AI评）、售后率；取不到写数据不足，不套别的店阈值
- **对照锚点（可选）**：有老店教训、标杆店或前后阶段时，加一张「维度/锚点/本店/判断」表，比空泛的行业对比更有用

### 6. 产出本地报告（不发布内部平台）

- 骨架（完整诊断，板块不许删，指标到数据源的映射见 `references/full-diagnosis-matrix.md`）：结论（含三条核心）→ 行动清单 → 概览核心指标（18 项，含对比期与基准备注）→ 铺货节奏与货盘结构（上架节奏/品类/价格带/动销/集中度）→ 经营与流量（来源/搜索词/店内流转）→ 商品诊断 → 广告诊断（日度/漏斗+三级类目基准/产品线/活动依赖/余额/稳赚/红包现金/对照锚点）→ 货端质量（信息分/价格星级/店铺星级/真实好评率/售后率/稳赚分层/SKU点名）→ 行业对照 → 风险与数据缺口 → 数据说明
- **分层压缩**：正文只留结论/动作/判断/小表证据，大表（分日全量、全指标、TOP30+）放 Excel 并注明去向；商家会逐行看的表（计划明细、商品 TOP）不压缩
- **发布前跑结构闸门**：`python -X utf8 scripts/validate_report.py --md <md> --xlsx <xlsx> --shop-id <id> --shop-name <name> --full`，必须 0 FAIL。闸门查店铺ID（开头+数据说明两处）、标题带店名、章节齐全、A/B/C 行动、数据说明三要素、铺货/货盘/价格带/货端质量/行业对照/数据缺口板块、无 `~` 区间、无占位符、Excel 表数与店铺ID行
- **最终回复固定三要素**：报告链接、Excel 文件、一句话结论；发布失败必须明示原因，不允许只交本地文件不解释
- Windows 上若 `D:/Miniconda3/python.exe` 不存在，joyspace_cli.py 会找不到提取器：先 `$env:JOYSPACE_PYTHON=(Get-Command python).Source` 再跑

## 常见坑

- **切店必须换干净浏览器**：换下一家店时，上一家店的 Chrome 若仍占着端口，新实例绑定失败、就绪检查命中旧实例，后续所有采集会**打到上一家店**（2026-09 云擎四店实战踩中，靠 logininfo pin 对不上才发现）。现行 `shop-browser.ps1` 每店独立 Profile + 自动选空闲端口，并在就绪后核验 profile 归属；多店批量任务仍应在每店开跑前用 `common/logininfo` 回读 pin 核对一次身份。
- **含中文的 .ps1 必须存 UTF-8 with BOM**：PowerShell 5.1 对无 BOM 文件按 ANSI/GBK 解析，中文注释的乱码会**静默破坏后续语句的执行**（2026-09 实测：同一段过滤逻辑，无 BOM 版 `$mine` 判空、加 BOM 后正常；去掉中文注释也正常）。用 apply_patch 等编辑器改完 .ps1 后必须补 BOM（`[IO.File]::WriteAllText($p,$t,(New-Object System.Text.UTF8Encoding($true)))`）
- PowerShell 写 JSON 计划必须无 BOM：用 `[IO.File]::WriteAllText` 配 `UTF8Encoding($false)`；make_plans.py 已处理
- PowerShell 下 python 内联脚本读中文路径会 GBK 乱码报错（路径变 `??`）：改用相对路径，或设 `PYTHONUTF8=1`
- **PowerShell 命令行传中文会被安全层间歇性吃成 `?`，且 `?` 在 `-like` 里是单字符通配符**（2026-09-29 实测：中文 profile 名损坏后，任意店窗口开着都误判 profile 占用）：中文参数/路径不要经命令行传递——从配置文件读取或用 glob；PowerShell spawn 与 stdin 管道传中文同样会损坏。详见 skill `o2-windows-runtime` 的完整沉淀
- **任务/采集结束必须释放 headless 占用的店铺 profile**：headless Chrome 实例锁住 profile 后，商家/用户打不开该店铺浏览器窗口会被卡住。长采集脚本结束时显式关闭自己拉起的 headless 实例；接管的可见窗口按授权规则重新打开
- **给「尚未进采集配置」的店铺做一次性探测时，`release_store_browsers()` 帮不上忙**：它只遍历配置内的店铺（2026-09-30 紫气企业店接入实测：jzt 未激活探测失败后，配置外的 9235 headless 实例残留锁 profile，用户打不开店铺窗口）。任务局部脚本必须在自己的 `finally` 里按 profile 路径 + `--headless` 显式清理自己拉起的实例，不能依赖按配置遍历的释放函数
- **全新店铺的商智接口按「新账号态」返回**（2026-09 云擎四店验证）：tradeSummary 不传 `indicators` 返回 `size=0/data=null`（易误判为无成交）、indexSummary 直接报「indicators不能为空」——两者都必须显式传 `indicators` 数组；flowSource 对这类店一律 10001 参数校验不通过（未解，报告写明渠道拆分缺失）；行业大盘 20001 无权限（店级权限，行业对照改用京准通行业接口）。探测顺序：先用 productTable 拿真实成交与类目，再用 7/8 月单查确认是否新店，再补显式 indicators
- **新账号态 indexSummary 补充验证**（2026-10-23 圣迪欧实测）：indexSummary summary 端点显式传 4 指标 indicators（ord_amt/ord_qtty/uv/page_cnt）后可用，但 trend 端点同参数仍 10001——分日序列拿不到时用京准通广告分日（isDaily=True）替代呈现，报告写明全店分日成交缺失
- **T+1 出数日历月会漂移，取数前先探最新可用日**（2026-10-19 四店实测）：9 月批次 T-1（9/29）当天可查，10 月批次 10/18 当天 GE 与商智两侧均无返回（次日 10/23 确认 10/18 有数）——不要假设 T-1 恒可查，先用单日 query 探测，本期统一截至最后一个有数日
- **京准通分日报表 `obys` 不支持 `day`**：make_plans 旧版生成 `day|asc` 会 400「入参obys排序错误」，已改 `cost|desc`（isDaily=True 已按日分行）；跨店复用计划文件时注意 `pinIds` 是生成时的店铺账户号，换店必须重新生成，否则 400
- 商智/京准通口径不同（新快车 vs 广告点击 30 天累计），报告数据说明必须写口径说明
- 行业接口缺 `clickOrOrderCaliber/clickOrOrderDay/giftFlag/orderStatusCategory` 会 400「跟单口径缺失」
- 京准通 cid3 与商智 cid2 不是同一 ID 体系，分别从各自页面查
- 首页「今日快照」是 15 天口径，与月报 30 天口径不可比，只作观察
- zguard 循环约 30 分钟有效期，长任务中途过期就重启一次
- **账户余额 XHR 重放不可用**（`financecore/*/allbalance/get` 返回 -2011 loginMode is null）：可靠做法是后台标签导航 `jzt.jd.com/home` 读 DOM 文本里的「投放账户总余额/可用余额」（dongyue/home-balance.js、tools/jzt-balance.js 模式）

