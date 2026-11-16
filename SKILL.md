---
name: heideng-ops-agent-merchant
description: 京东 POP 商家运营总调度，直接调用包内成熟店铺连接、信息分素材、短标题自动导入、上架复刻、实拍、图片刷新、素材到手价采集、比价改价和经营广告诊断 Skill。
version: 0.3.0
---

# 黑灯运营智能体商家版

这是成熟 Skill 的商家化交付，不是另一个业务引擎。商家描述任务，Agent 使用本包实际安装目录执行；不要让商家手填 Profile、敲内部命令或粘贴凭据。

## 安装与连接主链

1. Agent 在源码/解压目录运行 `python install.py --host codex --with-runtime --with-official`。JoyCode 改为 `--host joycode`；WorkBuddy/其他宿主使用其实际 `--skills-dir`。独立 Skill 名为 `heideng-ops-agent-merchant`，状态为 `~/.heideng-merchant`；不覆盖内部版和个人 Skill。
2. 已有本商家环境的授权：`python scripts/merchant.py run connection -- ensure-shop --shop "目标店铺" --no-auth`。成熟连接器实时获取身份、复用可用 Profile；不要因任务切换重复扫码。
3. 确实缺授权时，先取得该店的新授权许可，再运行同一 `ensure-shop` 去掉 `--no-auth`。返回 `awaiting_auth` 不代表失败：按原 HostBrowser 动作让本人扫码，再在同一浏览器会话完成官方 OAuth，不另启授权系统、不复制 Cookie。
4. 原 HostBrowser 默认由宿主操作。Agent 通过原连接器的本机私有 `/api/browser-action` 读取当前动作、执行真实页面动作，并以 `/api/browser-report` 回报同一 jobId/actionId 的真实 contextId、owned 和身份。也可用包内 `scripts/browser_bridge.py` 对接实际宿主控制器。动作 URL 只在内存中处理，不记录凭据；不把“标签存在”当成已登录身份。具体契约见 `mature/connection/app/browser_adapters.py`。
5. 拿连接器返回的 Profile/venderId/shopName 执行成熟业务。不用 default；原本的核店、写入确认、回查、未知结果不重提规则不变。浏览器任务使用商家状态目录内的真实持久 profileDir，连接器保存后可交给 POP 自动导入；没有目录时由宿主建立本任务专用上下文，不能复制工作浏览器。

## 实际派发

统一命令：`python scripts/merchant.py run [--entry scripts/已登记入口.py] <能力> -- <原成熟参数>`。
可用入口来自 `mature/*/provenance.json`，业务流程看同组件原工作说明/源码。没有注册的能力不能回落旧 builtin 运行时。

| 任务 | 派发能力 | 实际执行来源 |
|---|---|---|
| 连接/复用授权 | connection | linker.py / browser_auth.py / shoplib.py |
| POP 信息分素材 | materials | jd_material_agent.py / pop_workflow.py |
| 短标题生成与自动导入 | short-title | 原冻结 SKU 范围、agent-text-file、complete_short_title_import → import_short_titles |
| 一键上架 | listing | jd_product_pipeline.py；已有草稿用 publish_local_draft.py |
| 链接完整复刻 | link-replica | hot_replica_preflight → apply → hot_replica_publish |
| 实拍上新/矩阵上新 | photo-listing / matrix-listing | photo_listing.py / matrix_listing.py |
| 主图/详情图/SKU图 | images / image-refresh | image_patch_update.py / 原 refresh 任务链 |
| 透明图/白底图 | materials | 原平台批量抠图、本地可选抠图和绑定路径 |
| 素材与到手价采集 | collection | 原 prepare_batch、collect_signed/click、batch_driver |
| 同规格比价/确认后改价 | comparison / price-update | same_product_market.py / jd_price_adjustment.py / jingmai_api.py |
| 经营广告诊断 | diagnosis | 原 L1 及 make_plans → sz-fetch/jzt-run → validate_report |
| 已有视频本地交接 | video-handoff | 原 video_publication.py |
| 已有视频上传绑定 | video-binding | 原 video_handoff.py → photo_video.py |

短标题默认使用成熟的宿主生成路径（`--text-model agent --agent-text-file <真实范围文件>`），随后继续原自动导入，不交给商家手工导入。独立外部文本 API 未配置，不改回公司 Key。
复刻预检使用 `--analysis-file` 接收宿主对实际源图的分析：`{"drops":[{"i":1,"reason":"实际原因"}],"continuity":{"spec":"实际统一风格","pages":[{"i":1,"title":"实际内容","prev":false,"next":false}]}}`。pages 对应剔除后的保留页；原内容/页序/落位/品牌规则不变。不能用假分析或空文件代替实际图像判断。

## 模型及视频边界

- 图片只用 LTS4AI `https://api.lts4ai.com/v1` / `gpt-image-2.5`，请求实现复用 sufy-image2。商家自己的 Key 由安全输入入口 `python scripts/with_image_key.py <业务命令参数>` 传到本次进程；不读公司或其他 Skill 的 Key，不写源码、日志或聊天。
- 外部 AI 视频生成渠道未配置：不能声称“已替换”，不能退回灵境公司额度。此限制不应阻断已有视频的本地交接/上传绑定，也不能静默改做免费拼接。
- 已有真实候选（视频、封面、原 QC/口播信息）可以用 `run video-handoff -- publish <listing-package> --run-id <真实run> --video <该run候选视频> --cover <候选封面> --metadata <真实复核元数据>`，直接调用成熟发布 API。候选需在包内 `.main-video/runs/<runId>/candidate/`；不得手改 manifest SHA/QC/taskId 伪造完成。
- 随后 `run video-binding -- --manifest <manifest.json> --confirm BIND_MAIN_VIDEO`。有口播时沿用原试听确认、同文件 SHA 和上传/转码/逐 SKU 绑定回执；不是多加一套商家门禁。
- 采集和诊断沿用原任务浏览器。需要实际非敏感 CDP/context 配置时由宿主建立；不得猜端口、复制员工浏览器或输出 Cookie。

## 当前边界

公司员工自营、招商、GE/EasyBI、JoySpace/京ME 不纳入商家能力。未配置的独立文本/视觉 API 用成熟宿主生成文件路径；外部视频生成仍未配置。新类目规则、平台授权品牌/字段仍按原 Skill 获取实际引用，不编造。

用户已要求停止额外验证：本轮不再运行测试、扫码、店铺写入、付费生成或安装演练。成熟业务继承原历史使用依据；不要把这一点写成“本次真实商家验收通过”。
