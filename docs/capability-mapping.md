# 能力迁移表与真实请求链

日期：2026-11-15。分类表示技术迁移工作量，不表示对外分发/商用许可已经获批。登记不是能力白名单。

## 1. 优先能力

| 能力 | 结论 | 数据与商家权限 | 模型/执行链及实际缺口 | 选定或候选源码 |
|---|---|---|---|---|
| 店铺连接 | 需适配；官方 CLI 核验原语可复用 | 商家本人京麦登录 + 同会话官方 OAuth；每店非 default Profile | 已装 linker 1.0.2；官方下载/校验有实现，但文案含员工 JoySpace 开白，默认登记目录共享；需商家命名空间；外网新 OAuth 未验收 | ctzlyj/jingmai-cli-linker（private，无 LICENSE）/京麦官方 CLI |
| POP 信息分维护 | 需适配；优先评估已有商家包 | 商家报表/可信主图、本人图片空间/官方素材权限 | 内部 jd_material_agent/pop_text/pop_attrs 实际走公司网关，不可带入。已有 jd-material-merchant 可复用 Excel/图片算法，但有未知状态重试、无费用总闸门、历史固定模型、缺视觉复核；不能原样接入 | ctzlyj/jd-material-merchant-skill（MIT；模板另有权属）优先，jd-material-pop-skill 仅只读参考 |
| 一键上架/链接复刻/实拍上新 | 需商家薄分叉；官方发布协议与纯本地部分可复用 | 自有/有授权素材 + 目标 POP 店铺授权；来源商品页面/本地包 | 旧 photo_generation 和 company_jpeg_edits 写死 company 模型并读取员工环境/注册表；matrix 也取内部 Key；bootstrap 内网安装；photo_video/video_handoff 硬依赖 11190。分别替换，不只改 env | ctzlyj/jingmai-hot-product-mover-skill（MIT） |
| 批量主图/详情优化 | 需适配，完整原包不发行 | 商家本人京麦、商品/图片空间权限 | generate.py 实际公司网关；bootstrap 有员工 JoySpace，_common 读取 JD_LLM_API_KEY；重做商家生成入口并由官方工具承接更新 | ctzlyj/jingmai-batch-image-refresh-skill（private，无 LICENSE） |
| 店铺经营/广告诊断 | 部分可复用，需移除员工层 | 官方只读 CLI；本人商智/京准通或商家上传报表 | 旧 0.2.0 的 L1 可评估、L2 验证本店权限；L3 黄金眼代理、EasyBI/ERP、JoySpace 发布全部排除。另一个同名 repo 现为 jd-tengfei-diagnosis，不能误认同一版本；均未见许可证 | ctzlyj/jd-store-diagnosis-skill（旧0.2.0）；ctzlyj/jd-store-diagnosis（新布局，需单独许可） |
| 商品素材/到手价采集 | 核心可复用，安装与浏览器衔接需适配 | 合法商品前台、本人可访问页面；不绕过风控/登录，素材使用权独立核对 | 不必用生成模型；采集的 SKU 顺序/真实到手价/断点验收可保留；移除内网 bootstrap，适配外部浏览器，不把原整包称为直接商家可安装 | ctzlyj/jd-hot-link-collector（MIT） |
| 同款比价/改价 | 查询/精确规格匹配可复用；写入需商家门禁 | 合法商品前台 + 本店官方 Profile；必要时用户提供图片 | 本地源没找到公司模型调用；识图若宿主承担仍需合法外部选择。价格查询与真实改价分离；每次绑定计划和店铺，结果不明先回查；private 源不能假定商家可下载 | ctzlyj/jd-competitor-price-adjustment-skill（MIT，private） |
| 电商视频 | 需安全包装与持续同步，固定上游 | 真实商品前台或本地 listing-package；自有合法外部账户 | 上游0.3.0有方舟/Yeta/LibTV候选、无视频默认值；保留 oxygen-h3 内部入口。需封禁、未知幂等、原子预算、脱敏、配音回退和 manifest 交接；生成不等于上传绑定 | ctzlyj/jd-pop-main-video-skill（private，无 LICENSE） |

## 2. 不纳入默认目录

京喜自营邀约/信息分/经营广告、员工招商、内部商家联系方式、黄金眼代理授权、EasyBI/员工 SDK、JoySpace、京ME、集团登录及公司模型平台。没有对应商家合法数据时用上传报表或标记不可用，不寻找员工权限回退。

## 3. 模型请求链证据（审计代码位置）

以下位置指只读源码/安装副本，不是当前项目待发行代码。

- 信息分：scripts/jd_material_agent.py:81 注册公司 provider；scripts/pop_text.py:37 文本请求；scripts/pop_attrs.py:148 属性文本请求；scripts/secure_launcher.py:67-71 读取员工环境。透明图/白底/场景/卖点共用图像主循环，不能只换总调度 Key。
- 上新：scripts/photo_generation.py:10,74-79 固定公司域名且回退注册表 Key；scripts/company_jpeg_edits.py:56,120 公司图片请求；scripts/matrix_listing.py:462,560 公司凭据；scripts/photo_video.py、scripts/video_handoff.py 旧视频发现/验收协议。
- 主图刷新：scripts/generate.py:118 公司生成请求；scripts/_common.py:126 员工环境；scripts/bootstrap.py 员工安装/开白依赖。
- 旧诊断：SKILL 的 L3 与 scripts/ge-sz-fetch.py、easybi_shop_query.py、shop-browser.ps1 是员工层；新诊断的技能名/布局不同，审计不能合并。
- 商家信息分候选：jd-material-merchant/scripts/jd_material_agent.py:49-60 LTS4AI 固定历史配置；:537-575 _request 对超时/TransportError/5xx等最多4次请求；:579-633 存在 jd-internal 响应分支但当前配置是外部；语义重写/安全策略换图还会增加调用。预算/数量/未知状态必须由商家客户端替代，不直接运行原 generate。
- 视频：providers.Runtime → chat_text/image；identity、ai_ad、qc_video 都调同一 Runtime；video_job → providers.make_video；voiceover → edge-tts，异常回退 audio_track 系统音色；align_subs → Windows Speech ASR，非外部付费模型但需要本机可用性/许可与质量验收。

## 4. 外部来源与许可证证据

| 仓库 | 本轮 HEAD | 许可/发布状态 |
|---|---|---|
| ctzlyj/heideng-ops-agent-skill（本地只读基线） | 13692b759bd52e35c3670cf8fad5330e1bf2b576 | 内部1.5.4，仅参考 |
| ctzlyj/jingmai-cli-linker | 1c438fc5419cd86f709cc4a501325782fd4a1e36 | private；未见 LICENSE |
| ctzlyj/jd-material-pop-skill | b56b22376db88182352d3f64ea3e9752d4ae5677 | private；未见 LICENSE |
| ctzlyj/jd-material-merchant-skill | bf3568e4d04819b74c6a2e59c20dca9a2f1e2913 | public，MIT；模板 NOTICE 保留原权属 |
| ctzlyj/jingmai-hot-product-mover-skill | 3ee08af2f3970f88d39756f1906040efe75117dc | public，MIT |
| ctzlyj/jingmai-batch-image-refresh-skill | 8a2f3df185562b1f2f27859a90080d19b2f259cf | private；未见 LICENSE |
| ctzlyj/jd-store-diagnosis-skill | 42971c041248bab27f4d627357dcc475f848eb75 | public；未见 LICENSE |
| ctzlyj/jd-store-diagnosis | bc5a0fb5f01f0867a269388e076539a526cf330f | private；未见 LICENSE，新 jd-tengfei-diagnosis 布局 |
| ctzlyj/jd-hot-link-collector | 90ef8dfd8455848d539d22560ae26ba8bac52e2a | public，MIT |
| ctzlyj/jd-competitor-price-adjustment-skill | 43bdf6790fe3c8a5b89c217edcaefabf670cbc2c | private，MIT |
| ctzlyj/sufy-image2 | b2b5724d77787b49469f43308f9e1de57438ee08 | public，MIT；本机副本与该 HEAD 未证明一致 |
| ctzlyj/jd-pop-main-video-skill | 29548089f7b71ac77ddb584caac0966a98df24ab | private；未见 LICENSE |

本机已装版本：linker1.0.2；内部 registry 仍记1.0.0；信息分2026.11.207；上新1.2.6；主图刷新1.4.5；采集1.0.4；视频0.3.0。比价/sufy未发现明确版本字段，不编造版本。仓库 HEAD、内部 registry 和安装包声明分开记录，不默认它们是同一快照。

## 5. 分发缺口

无许可证的代码不默认复制或对外分发；private 仓库不能当作任何商家可访问的安装源。第一阶段可完成独立核心与 mock、下载发现/哈希核验、候选适配接口；没有分发许可的依赖保持 license-blocked。模板、字体、FFmpeg、抠图模型和 edge-tts 服务商用条款仍需核对，不因免费/本地就声称已许可。
