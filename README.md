# 黑灯运营智能体商家版

> 当前为私有开发检查点，目标仍在实施；尚未宣布正式上线完成。原生商品/SKU/健康分查询、价格规划/执行/待审与线上回查及新OAuth自动接管代码已补齐，验证为离线/SDK等级；真实商家签发、完整发行回测和业务实机链路仍待验收。

商家安装一个GitHub能力包，只描述目标，Agent组合官方京麦、合法浏览器和本地工具执行。不是SaaS，不代付，不依赖京东员工ERP/内网SSO/SkillHub/公司模型Key。

## 安装提示词（发给你的Agent）

请安装 GitHub 仓库 ctzlyj/heideng-ops-agent-merchant-skill 的黑灯运营智能体商家版。复用当前Agent已有的GitHub读取权限。当前没有正式Release：读取私有codex/merchant-foundation分支，核对docs中的最新开发检查点commit与验收证据，在该commit重建独立ZIP、验证清单SHA256后安装，不将源码检查点当正式发行版。正式Release发布后优先下载经过审核的发行ZIP并核对SHA256。由你执行install.py，将唯一入口heideng-ops-agent-merchant安装到当前宿主的独立skills目录，再运行onboarding带我上手。不要改动内部版或使用内部SkillHub，不要让我手敲命令、复制Cookie、授权码或Key。店铺相关功能缺官方CLI时，你从京麦官方公开通道校验安装；需要新授权时，我只扫码并完成本人确认。

**当前先私有交付**：安装者必须已有仓库读取授权；不能把私有链接说成任何商家均可下载。公开、公司成果分发和第三方商用许可由负责人另行决定。

## 可直接描述的目标

- 帮我核对这份商品资料并保留全部规格，整理成实拍上新包。
- 分析这份经营和广告报表，指出数据缺项，不自动投广告。
- 整理这些同规格商品的逐SKU到手价，出TOP10和待确认调价方案。
- 核对这批商品信息分和素材缺口，复用已有合规图片。
- 采集这些商品的真实SKU顺序、到手价、主图/详情素材，保存成包。
- 用我提供的视频和封面准备主图视频交接，先复核再确认绑定。
- 连接我的POP店铺并查询商品；任何写入给我看明确范围再提交。

## 状态必须说清楚

生图来源已选定为LTS4AI（https://api.lts4ai.com/v1），模型gpt-image-2.5；已复用现成MIT客户端接入文生图、参考图编辑与本地图片保存；商家安全设置自己的Key并批准本次数量/预算后可执行，真实付费调用尚未实测。详见 references/lts4ai-image.md。视频生成服务仍待选择：不会偷偷用公司网关，也不会静默切换收费平台。已有素材、宿主策划/识图、报表分析、查询和业务准备仍可使用。官方权限和网页登录需商家本人授权。视频生成、本地文件、上传、受理、线上生效是不同状态。

已实现独立安装/校验/回滚、官方同版大载荷stdin薄适配（公开源标deprecated，版本/SHA/批准绑定；未实测真实上传）、原生图片空间/分类/上传与原回执ID回查（未实测真实店铺），原生商品/SKU/健康分分页查询及京东价PATCH（待审和线上分开）、官方CLI下载验证、非default Profile身份绑定、任务范围批准/unknown去重、本地经营分析、同规格比价、素材审核、实拍包和已有视频交接。新授权由独立worker承接同会话扫码/OAuth；当前仅Windows开放带凭据CLI执行；macOS新授权和已有授权查询均因官方token刷新可能产生secret argv而禁用，安装/离线流程仍可用。浏览器采集和商智京准通取数由当前Agent使用商家授权会话执行，不要求安装公司浏览器插件；实际平台链路验证进度见docs。

## Agent内部命令（商家不需要执行）

python install.py --host codex --with-official
python scripts/merchant.py onboarding
python scripts/merchant.py doctor --install-cli
python scripts/merchant.py route "诊断店铺广告"
python -m unittest discover -s tests -v

可选XLSX读取使用公开Python依赖openpyxl；缺失时由Agent在商家独立运行时安装，不要求另装Skill仓库。核心安装/JSON/CSV流程仅需Python3.11+标准库。

## 安全与许可

只使用当前仓库的独立代码，不分发无许可证内部业务源码、运行记录、个人路径或凭据。官方工具从官方源校验下载；第三方工具/模板/字体等权利不由本仓库重授。没有获得公司成果对外分发和收费许可，不能将此视为个人收费项目。


已有合规图可走原生素材规划/上传/回查，不调用生成模型；首次图片解码由Agent按需准备公开PyPI Pillow的独立运行时。图片空间保存与商品绑定分开，详见references/native-materials.md；目前为私有开发验收等级，真实账号权限与上传未实测。

已有商品可读取全SKU编辑模板，生成只改已有主图/逐SKU图槽位的无损本地草案（全量SKU、销售属性、详情和未知控件保留），详见references/native-product-schema.md；此草案命令本身不写店铺；需要整版提交、详情编辑和图片绑定字段回查时，使用下述独立来源基线/两阶段编辑链路，真实线上状态仍待商家授权验收。当前价格规划不再受旧18000字符argv估计限制，按实际官方transport选择stdin；仍以完整旧值/待审/线上范围批准和回查，不截SKU。

新品可从本商类目/三级品牌/销售属性/完整模板进入全SKU校验与条件提交链；已有照片无须生成模型。校验和提交都需明确范围批准，未知不重放，原applyId/productId不制造链接；源码和限制见references/native-publishing.md。当前为开发验证等级，真实商家新建与全线上字段仍未实测。

既有商品整版图片/详情优化新增来源基线与原申请单/全字段回查链路，见 references/native-full-edit.md；必须保留全 SKU/原字段并经官方 validation 和用户明确许可才写入。当前为合成/离线契约验证，不承诺未验证类目模板或真实线上状态语义已兼容。

原生模板自动编译入口见 references/native-template-compile.md：Agent 从同店原完整详情与原规则的字段声明准备全 SKU 来源基线，不让商家手填 schema/bindings/sale-sources；原始规则和编译证明保留，重复准备沿用同一编辑意图。未声明或无法证明的字段拒绝，不称所有线上模板已经实测。

**信息分口径仍需实测对照**：官方目录将 health-infos 定义为“商品信息健康分”，可用原生 healthScore / improvementList 做诊断；与京麦页面 commodity-score 的逐行等价性尚未验证，不能仅凭名称断言相同或不同。已补齐原生 SKU 缺失素材槽位的审计、批准、绑定及全查询范围回读（仅合成测试）。图片空间保存、整版编辑、素材绑定、审核通过和分数重算分别记录。详见 references/native-sku-materials.md。

全店在售素材/信息健康审计新增完整来源入口：在售商品→全部兄弟SKU（包含离线兄弟）→一次原生health数据集→全部支持素材→前后商品/SKU集合交叉核对。摘要只返回完整范围计数，明细保存在本地且可分页筛选；分值未知、未取到和缺失分开，不补0、不自动写店铺。仅合成/安装验证，真实权限/接口未实测。详见 references/native-shop-material-audit.md。

## 已有视频的本地交接

Agent可独立全帧/音轨解码MP4、检查真实封面并绑定视频/封面/商品hash；视觉和声音须实际验收，不能凭`technicalPass=true`提升可绑定状态。运行时仅按需从公开PyPI安装，不生成/付费调用。详见`references/local-video-handoff.md`。本地就绪不等于原生上传、SKU绑定或平台审核成功，原生上传/保存的受批准会话已接入（见`references/native-video-delivery.md`），SKU绑定已接入私有研发适配（见`references/native-video-binding.md`），仅经离线/合成验证，真实平台未实测，真实商家链路另获批准才实测。

### 视频会话与更新安全

独立上传会话和 SKU 绑定的原始尝试、回执及批准均纳入更新门禁。有 unknown、未决阶段、孤立/损坏证据时，安装和回滚不会先清理恢复现场。新视频计划保存运行时版本；更新后的旧未执行计划不会发起业务写入。只有尚无任何业务尝试的本地计划，在明确取消原范围后，Agent 才可保留取消证明并重新规划。不能取消远端未知结果来重提；详见 `references/native-video-delivery.md`。以上边界由合成链路验证，不等于真实商家上线验收。

### 整店可用素材统一执行

Agent先取得全部在售商品、完整兄弟SKU和素材来源，再把已有核验上传图/真实卖点放进一个明确根范围；一次批准后逐商品<=50SKU分块、独立原件留账、原字段读回和恢复，unknown不重提或推进剩余块。默认全部支持槽位，缺素材/原有空/待审/驳回/未知状态完整报告，不能只处理有分数的行或把部分成功称整店完成。入口和明确边界见 `references/native-shop-material-execution.md`。整店驳回/空槽的明确修复已接入：旧状态/理由与原图字节留证，新图不得换URL复用旧字节，逐块未知不重提，详见 `references/native-shop-material-repair.md`。当前仅合成/安装验收，生成来源、短标题与真实商家验收仍未完成。

## 短标题自动导入的前置阶段

已增加完整原库存/health问题核对、宿主审核稿的规划/分页、5000行分块与安全模板中间产物。分数无效/素材读取失败不会被当成标题不存在；离线/未知/无问题完整保留，模板不从内部缓存复制。详见 `references/native-short-title-planning.md`。此阶段明确planning-only，不具备浏览器上传/创建任务/回读，不称已导入，也不要求商家默认人工上传；完整自动导入仍是下一阶段必须完成的工作。

### 短标题原生导入与处理结果API（B2/C1-C2研发）

已接入精确root批准、原抽屉上传/创建实例、独立回执与查询恢复API，以及原任务结果文件的只读获取、完整逐行处理结果和独立观察/回执/head校验。CLI 已有持久 worker 的 start/精确 approve/execute/recover/results/effects/status/command-status/stop 与确认关闭后的 readonly resume；用法见 references/native-short-title-worker.md。C3 完整正式审核/health/门户回读仍必须补齐。rowResultsVerified只说明原完整批次处理结果，不是标题生效或重试批准；unknown、审核延迟不重投。详见 references/native-short-title-import.md 与 references/native-short-title-results.md。

原范围实际短标题/health 回读与持久化证据已接入部分原生来源 API；持久 worker 已接入；完整正式审核/门户/health 与确认失败子计划仍待完成，不称整店生效。Agent 用法与历史 effects 分页见 `references/native-short-title-effects.md`。
