# 成熟能力复用迁移 / 2026-11-16

## 已核对基线与执行边界
- 内部总调度 1.5.4 / 13692b759bd52e35c3670cf8fad5330e1bf2b576；只读，未修改。
- 商家源码与远端 codex/merchant-foundation 均为 0.1.5 / 10132cf831d26a4e2984540665f418951acfbb52。
- 原工作区 18 个已跟踪修改及 5 个新实验文件留在原位；隔离分支 codex/merchant-mature-reuse 从已推送 HEAD 开始，不包含实验。
- 决策：退出 builtin-independent-merchant-runtime 的业务派发，恢复成熟源码入口；不把官方 CLI 底层相同误称业务复用。
- 不进行扫码、新 OAuth、店铺写入、付费生成，不发 Release 或通知商家。

## 对照表
|能力|成熟源码与实际版本|0.1.5 差异|迁移动作|必要验证|
|---|---|---|---|---|
|连接/复用授权/同会话 OAuth|ctzlyj/jingmai-cli-linker 1.0.2 / 1c438fc；scripts/linker.py → app/server.py、shoplib、browser_auth、browser_adapters|自建 auth_* 与多重任务门禁|恢复成熟连接器；只隔离 JDO_HOME、JINGMAI_LINKER_HOME、端口和宿主桥接；源码无 LICENSE，待明确商家分发许可|独立目录、成熟 doctor/resolve/verify 真实入口；真实签发待授权|
|POP 信息分/素材/短标题|ctzlyj/jd-material-pop-skill 的 jd-material-pop 2026.11.207 / b56b223；jd_material_agent → pop_workflow.complete_short_title_import、pop_browser、pop_safety|数十个新 short_title_* 状态机，自动导入缺口|恢复原自动导入与结果处理；仅替换模型、安装与状态目录；本源无 LICENSE，待许可|成熟函数/模板可达；LTS4AI 适配；真实导入未执行|
|上架/复刻/实拍/矩阵|ctzlyj/jingmai-hot-product-mover-skill 1.2.6 / 3ee08af；jd_product_pipeline、jdo_listing_mvp、photo_listing、matrix_listing|自建出版/完整编辑状态链|复用 MIT 源码；保留成熟核店与幂等；公司图像类换 sufy-image2 薄接口|原多 SKU 构造/校验/回查；离线包；未执行真实发布|
|主图/详情/逐 SKU 图|ctzlyj/jingmai-batch-image-refresh-skill 1.4.5 / 8a2f3df；image_patch_update、detail_patch_update；上架仓库也包含同源 patch|自建模板编译与二次门禁|优先复用 MIT mover 已有 patch；整店 refresh 原源无许可待确认；不再造模板编译器|原字段和 SKU 保持；真实编辑未执行|
|透明图|POP pop_cutout / 本地 rembg，原许可清单 cutout-license-sources.json|新 SKU repair 层|沿用原抠图；只隔离缓存，不引入公司 JoyAgent 回退|alpha/尺寸/许可及本地权重缺项分别记录|
|商品素材/到手价|ctzlyj/jd-hot-link-collector 1.0.4 / 90ef8df；原 native_page/observer → package_live/verify_batch|独立简化 collection 实现缺原生价格证据|复用 MIT 采集/清单/验收；O2-only 浏览器边界改成外部宿主入口|原 SKU 顺序、到手价、缺价/断点策略；真实来源登录态待验|
|同规格比价/确认改价|ctzlyj/jd-competitor-price-adjustment-skill 1.0.0 / 43bdf67|简化 compare/price 新链|复用 MIT 分析/改价/回查；浏览器边界移除 O2 和个人根路径|同规格原算法/确认后原操作；真实改价未执行|
|商家经营广告诊断|jd-store-diagnosis bc5a0fb 中 skills/jd-tengfei-diagnosis 与巡检库（无许可）|商品列表+静态建议被登记为诊断|仅迁合法 POP CLI 巡检与商家报表输入；员工 SDK/黄金眼/EasyBI 不迁；不可把未迁能力说已完成|可取指标和权限；已知数据缺口明确阻塞|
|视频生成/上传绑定|固定上游 ctzlyj/jd-pop-main-video-skill 0.3.0 / 2954808；上传绑定承接 mover 原正式代码|自建 video_delivery/binding 状态链；生成仍未配置|生成上游只审计、不调用内部渠道；复用成熟已有视频上传/回查；11190 交接换固定上游兼容层，保留完整性与试听要求|外部视频 provider 未定、上游缺许可；不能声称外部生成可用|
|生图|ctzlyj/sufy-image2 MIT，实际已安装 scripts/sufy_image2.py；旧商家已抽核心 b2b5724|核心已复用，但外围另有审批状态|保留协议核心，成熟业务只在模型接口做薄适配；固定 api.lts4ai.com/v1、gpt-image-2.5、商家独立 Key|请求合同/失败不回公司/不重提；未花费真实额度|

## 实施顺序（无需逐项审批）
1. 固定原实验文件哈希，建立隔离工作区；读取实际源码、许可与依赖（已完成）。
2. 先写回归：发布包不再含自建业务 runtime；派发必须解析成熟入口，依赖缺失明确报错，不回旧实现。
3. MIT 源码按 Git 跟踪文件的必要代码/资源选择性迁移，保留许可与逐文件 SHA。无许可源码先只读比对，不塞进安装包。
4. 恢复安装/连接主链，接入成熟 identity/profile/OAuth；有待确认的源码许可时只推进其它可实施项，不重造连接器。
5. 恢复各成熟业务入口，做 LTS4AI/宿主/独立状态目录薄适配；其它模型明确待配置。
6. 对实际变化执行离线真实源码、独立包安装/升级与子进程测试；真实副作用只在具体授权后执行。
7. 整体验证、源码渠道扫描、保护哈希复核、审阅后提交推送；新版本不复用 0.1.5。不宣布可重新内测，直到已知主链缺口修复或列为明确阻塞。

## 许可裁定
缺 LICENSE 不是重写的理由。本轮已向用户询问三个核心自有仓库的商家私有分发许可；未获得前不把无许可证源码装入分发包。可替代路径为仓库所有者明确许可必要业务文件，或商家在有访问授权的原仓库安装；后者不能冒称人人可从零安装。


## Current checkpoint, not completion

Version 0.2.1 distinguishes this source/adapter checkpoint from private 0.2.0 installation experiments. No Release or merchant notification. Three core source distribution permissions are still awaiting the owner's response; full goal remains active. No store authorization/write or paid model task has been executed.

Actual standalone checks include public PyPI dependencies in an isolated merchant venv, the public official Jingmai 0.3.7 binary/document checksum path, and installed mature command dispatch. These do not establish real merchant access, account Key/model availability, or macOS/WorkBuddy live readiness.

The first read-only review verified original Git blobs and identified three real integration bugs. They were reproduced and fixed: orphan old native-video evidence now always reaches the verified original old guard; image URL results use a packaged pure validator rather than an excluded legacy provider runtime; merchant browser argv configuration now reaches the original comparison transport. Real shared OS leases allow parallel mature tasks and exclude installation switches without a new business state machine. Isolated Python streams explicitly use UTF-8 because Windows `-I` ignores environment encoding settings.

Ruling: preserve reference/personal Skills unchanged. Reusable endpoint-redaction, Windows isolated-stdio and installer dependency findings are recorded in this project only; no personal Skill or internal SkillHub was modified.


## 用户确认后的裁定与实际进展
2026-11-16 用户回复“确认”，指向上一条明确请求：连接器、POP、整店刷新、诊断、固定视频必要纯业务代码/模板迁入私有商家仓库与安装包，不含运行数据/凭据/第三方受限资源。此前“待许可”是历史检查点，不再作为当前阻塞。
Ruling: 用 owner-authorized-distribution + 哈希许可记录保留范围，不伪造 MIT。已迁入连接器 1.0.2 和 POP 2026.11.207；其余迁移继续。
Ruling: 原授权/Profile/模板/自动导入/写入结果处理保留，只有公司 provider、个人目录和安装/宿主边界变化。文本/视觉未配置不造协议，不把 title 模型不可用掩饰为完成。
Ruling: 目前安装后业务源码已可达，但默认 HostBrowser 到 POP 持久 browser profile-dir 的衔接仍未完成，故不宣称从零业务主链已验收。
