# 商家成熟能力迁移交付 — 0.3.0 / 2026-11-17

## 执行纠偏

用户明确要求停止任何额外验证。本次收尾没有运行测试、浏览器 fixture、安装演练、扫码、新授权、店铺写入或付费生成。此前反复适配/验证耗时过多，不作为继续延期的理由。原成熟业务历史使用结果作为复用依据；没有把历史结果表述为本次商家真实验收。

代码位于隔离分支 `codex/merchant-mature-reuse`。原商家 `codex/merchant-foundation` / 10132cf 与其 23 个混合未提交实验保持原位；内部版 1.5.4 / 13692b 只读。

## 1. 必要修改保留

- 独立安装名、更新回执、商家 HOME/状态/CLI Profile，不覆盖内部版或个人 Skill。
- 限定分发清单及来源许可；不打包运行数据、浏览器 Profile、凭据、模型权重。
- 去除员工 ERP、内网 SSO/SkillHub、公司模型 Key/额度和内部平台依赖。
- 图片复用 sufy-image2 客户端核心，固定 LTS4AI / gpt-image-2.5，只使用商家本次进程 Key。
- Windows/macOS ARM64 官方 CLI 交付及宿主目录/进程薄适配；没有因“未验证”而额外禁止 macOS 原 CLI 执行。
- 原成熟核店、非 default Profile、用户写入范围确认、结果回读、防重复提交保留。低层发品/本地草稿/复刻入口共享原 matrix.publish_guard 的 SUBMITTING 规则，不另建审批状态机。

## 2. 重复实现退出

旧 builtin-independent-merchant-runtime 的自建 OAuth、标题生成/导入、素材操作、商品发布业务模块不再被 root CLI 调度、不在安装清单中、不作为 fallback。保留 Git 历史用于恢复，不对原工作区整批删除或 reset。

本轮没有给重建的业务状态机加状态。新增/适配部分是来源派发、独立依赖环境、外部图片 client 包装、任务浏览器输送、安装租约以及视频本地发布 API 入口。成熟业务计算与执行仍在原文件。

## 3. 迁移对照

| 能力 | 实际成熟来源/版本（commit短号） | 处理与入口 | 本次状态 |
|---|---|---|---|
| 连接/复用授权/同会话 OAuth | jingmai-cli-linker 1.0.2 / 1c438fc | linker + 原 browser_auth/shoplib；仅 namespace/宿主输送 | 已复用；不重测 |
| POP 信息分、素材 | jd-material-pop-skill 2026.11.207 / b56b223 | jd_material_agent/pop_workflow；图片外部适配 | 已复用；不执行写入 |
| 短标题及自动导入 | 同上 | 原冻结范围、host agent-text-file、complete_short_title_import → import_short_titles | 已复用；不是商家手工导入替代 |
| 上架/草稿发布/实拍/矩阵 | jingmai-hot-product-mover-skill 1.2.6 / 3ee08af | jd_product_pipeline/publish_local_draft/photo_listing/matrix_listing | 已复用；不执行发布 |
| 完整链接复刻 | 同上 | 原 hot_replica_preflight/apply/publish；宿主分析 JSON 只替换未配置视觉请求 | 完整原发布链已补回 |
| 主/详情/SKU 图 | mover 1.2.6 + jingmai-batch-image-refresh-skill 1.4.5 / 8a2f3df | 原分组、落位、刷新、绑定/回读；不重写操作引擎 | 已复用 |
| 白底/透明图 | POP 同上 | 原平台批量抠图/本地可选神经抠图/驳回修复 | 已复用；神经依赖是可选组 |
| 素材/逐 SKU 到手价采集 | jd-hot-link-collector 1.0.4 / 90ef8df | 原接口/点击/批驱动/原价选择与打包；仅 owned CDP/path 输送 | 已复用；未运行真实采集 |
| 同规格比价与改价 | jd-competitor-price-adjustment-skill 1.0.0 / 43bdf67 | 原规格/价格计算、官方改价、确认和回执 | 已复用；未执行改价 |
| 经营/广告诊断 | 真正内部调度的 jd-store-diagnosis-skill 0.2.0 / 42971c0 | 原 L1/L2，make_plans → sz-fetch/jzt-run → validate_report | 已复用；员工 L3 排除 |
| 视频本地交接 | jd-main-video-batch-skill 1.1.3 / 40d664e | 原 video_publication/check_main_video；薄入口 local_handoff | 已复用；不运行付费生成 |
| 视频上传/绑定 | mover 1.2.6 / 3ee08af | 原 video_handoff/photo_video 与源视频 automate_main_video | 已恢复本地交接，不再整体 blocked |
| 图片请求 | sufy-image2 / b2b5724 | 原 client 核心，LTS4AI gpt-image-2.5 | 已复用；未执行付费调用 |

完整 SHA、原/适配文件差异见每项 provenance.json。旧 portable 诊断分支不是当前 L2 来源；旧 0.2.x 检查点文档属于历史记录，不覆盖本表。

## 4. 从零安装和任务说明

商家对 Agent 说：安装商家版，然后连接目标店铺。Agent 执行：

```text
python install.py --host codex --with-runtime --with-official
python scripts/merchant.py run connection -- ensure-shop --shop "目标店铺" --no-auth
```

JoyCode 改 `--host joycode`；WorkBuddy 等用实际 `--skills-dir`。新授权得到本人具体许可后，去掉 --no-auth，按原 HostBrowser 回报同会话登录/OAuth。首次等待动作不是已授权/错误，Agent 要继续接宿主原浏览器接口，不能告诉商家“去别处授权后回来”。商家授权/状态随正常版本更新保留。

接着商家直接描述任务，Agent 用返回的实际 Profile/店铺身份派发成熟入口。短标题 host 生成完成后沿用原自动导入，不另走旧标题实验。图片任务得到范围/费用许可后，用 `scripts/with_image_key.py run ...` 的遮蔽输入传递商家自己的 Key，不进入聊天或磁盘。

已有视频和真实复核 metadata 通过 video-handoff 调用原本地发布，再由 video-binding 处理；无真实候选/口播确认/平台回执，不伪造字段。不得用手改回执、关闭完整性或 rollback→install 绕升级。

## 5. 明确边界/剩余环境项

- 外部 AI 视频生成渠道未确定，仍不支持商家端 AI 出片请求；不调用公司灵境/额度，不冒充替换完成。**本地已有视频交接与上传绑定不是同一个阻塞。**
- 独立外部文本/视觉 API 未配置。已保留原宿主生成文本/分析文件路线；不能拿公司模型 Key 兜底。没有宿主视觉/文本能力时，应明确该宿主缺项，不生成假结果。
- 店铺实际授权、平台类目/品牌/数据权限、商家任务浏览器的真实登录和持久目录是运行输入。已有本商家授权复用不会因为更新包重复扫码；不擅自复制内部/个人凭据来制造“已有授权”。
- WorkBuddy/JoyCode/macOS 的实机环境未在本次执行，不能宣称全部实机通过。官方不支持的平台/宿主无浏览器能力时明确报具体环境缺项。
- 员工自营、GE/EasyBI/内部招商、JoySpace/京ME 不在等价范围。
- 按用户最新要求，停止追加验证；没有实际执行的扫码/导入/发布/改价/付费生成不写“真实验收通过”。需要时由用户统一安排具体范围的从头内测，不对商家发通知。

交付版本 0.3.0。安装包完整性、来源 hash 和不同版本升级保护是正常打包/运行机制，未关闭；本轮不创建 Release，不公开仓库。
