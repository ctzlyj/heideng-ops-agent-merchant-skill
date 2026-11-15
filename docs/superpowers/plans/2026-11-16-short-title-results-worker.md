# 短标题 C + owned worker 实施计划（2026-11-16）

> **For agentic workers:** 使用 executing-plans，本线程内按测试→实现→核验推进；本计划不授予真实商家写入或外部付费授权。

**目标：** 在 B2 的不可变根及原始实例之上，接通原生结果文件、逐行结果、原范围回读与商家 CLI 的持续执行生命周期，不能用人工上传或导出文件替代闭环。
**基础：** 私有研发代码 02a909d126c7546e3efadab64b6379092890684e。B2 同代码已完成本地及实际私有 GitHub fresh clone 两组 601+6 验收；C1候选不计入该包。
**架构：** 保留 upload/create attempt 与一次 dispatch；C 仅追加只读证据与逐行状态。只有完整原实例的确认失败行可进入新修复计划；未知、审核延迟、缺失、计数冲突均不重投。
**技术：** Python 标准库 XML/ZIP、现有 task-owned Playwright 生命周期、官方 jdo-cli；不引入公司网关/内部员工依赖。

## 已确认源码证据与不能猜的部分

- 只读参考发现原任务 JSON 字段 jobExecFileRst，实例 jobExecId，上传对象 jobExecFileSrc，时间 jobExecTimeStart。jobId 仍是类型 ID。
- 原结果解析器检查首行列 SKUID / 执行结果 / 失败原因。这是历史源码契约，不是当前商家平台实测。
- 原实现将任意非“成功”状态当失败且未检查全范围，不能复用该推断。
- 未找到已核验的实时实际短标题、审核及门户分数完整契约。必须独立绑定实际来源，不能把 health.hasShortTitle、商品长标题或行处理成功冒充实际短标题。
- 真实 UI/JSON schema/pagination/result-file 模板仍需授权实测；当前开发和测试仅 synthetic，不访问真实 merchant 或模型。

## 任务 1：C1 bounded 原结果表解析

文件：新增 heideng_merchant/short_title_results.py；新增 tests/test_short_title_results.py 和合成 fixture。
- RED：未实现解析模块；然后最小实现，再窄 GREEN。
- 从原实例浏览器下载的 bytes 在内存解析。复用既有 XLSX ZIP/XML 图安全检查，不保存原表、签名 URL 或失败原文日志。
- 当前受支持表头严格 SKUID/执行结果/失败原因，文本 SKU 不接受浮点、科学计数或数字类型。重复/越界/遗漏/错 SKU、重复 XML 行列、公式/外联/实体/宏/压缩炸弹/无效 sharedStrings 均拒绝。
- 原 batch 全部 SKU 必须恰好一行；按原批次行序回报。只有字面成功/失败可确认；其他值 unknown，不从任务计数反推未列出的行。
- 正常成功/失败计数必须与原行数和完整结果相符。输出只证明处理结果，不证明 actual title / audit / health。
- 边界测试：全成功、混合失败、未知、不完整、重复/外店 SKU、numeric SKU、布尔/矛盾计数、失败文本含凭据、5000 行及越界、安全 XML/ZIP。
- C1 本身不生成 retry、不释放更新门禁、不伪称 rowResultsVerified 为整店生效。

## 任务 2：C2 原实例 native 只读观察和下载

文件：新增 short_title_result_browser.py；只调用 audited queryByPage 与原抽屉刷新/结果下载；不新增 REST。
- 每次同一主框架 fresh response、当前身份、actual ID、原上传 object hash/时间与原 anchor 一致；页缺少原 ID 只是不在该页，不是任务不存在。
- 单独读取原任务行的成功/失败/终态。控件须精确关联 actual ID，避免从其他行下载；字段歧义与多个结果候选阻断。
- 结果 URL 不落盘；使用原浏览器下载并限定 HTTPS/host/redirect/MIME/大小/完成字节。文件关联原任务，不用同名表替换。
- immutable observations 绑定 original anchor hash、current identity/page/body/result hash；同原件只读恢复，不上传/点击 create。
- 逐次刷新不覆盖旧观察；坏/丢失/孤立观察阻断，证据不完整必须 unknown。

## 任务 3：C3 原范围实际短标题/审核/health 独立回读

文件：short_title_verification.py 与相应原来源 contract。
- 固定原完整在售/兄弟清单与原 SKU 关系；现售状态改变不能抹去已写历史行。
- 实际短标题只能原生准确字段和版本，长标题或 health flag 不能替代；正式审核状态分开。
- 新完整 health 审计沿真实 held install guard；缺分数/缺材料不缩库存。门户 score 仅其原来源快照，不夸全店提升。
- 分类处理：处理失败 / 已接受待审核 / 实际一致 / 外部改动冲突 / 缺失未知。全部分页，不以 totals 替代行证明。

## 任务 4：确认失败行专属修复

- 只有完整原任务结果显式失败 SKU，且当前确仍需标题修复，才组成新子计划；原成功/unknown/awaiting review 永不自动重投。
- 新稿与新明确 approval 绑定原 parent/result hashes 和失败子集；任何变更重算 root，不混用旧 approval。
- 保留 parent 与所有失败/成功 history，门禁不能被新 plan/source 绕过。

## 任务 5：owned worker 与 merchant CLI execute 生命周期

- worker 复用本次任务的 merchant profile/context，不借用工作浏览器；整个原生会话持 install.lock；CLI prepare/approve/status 与同 worker 配合，不二次争锁。
- IPC 只接受非私密 import ID 与精确 root hash；有限命令/大小、单 home owner 和原 runtime。日志只有脱敏事件码，凭据/signed URL 不入 argv。
- Windows 后台无可见 console，浏览器只有需要用户认证时可交给用户；不自动登录/绕权。
- source capture→root prepare→wait explicit approval→execute→observe→verify 属同持续 lifecycle。首次未 dispatch 的 reopen 可重新 preflight；已上传 binding 丢失只能只读恢复，不能重传。
- 中断/未知/重启/返回丢失按原事件恢复，不以 PID/心跳超时推断“没写入”。停止确认后才释放 owner；残留 session/evidence 保持门禁。

## 任务 6：原件门禁与安装后全链验收

- 只有全部独立证据真实闭环的 terminal root可释放 install/update/rollback；所有历史原件保留且重算校验。
- 新 CLI installed synthetic smoke 包含 source→approval→单次上传/create→原实例结果→逐行观察→实际字段独立回读→状态。unknown/incomplete 保持不可重复提交。
- 最后统一 full regression + bundle audit + GitHub fresh clone + fresh HOME install；不每个微小子任务重复长全套。
- 当前 B2 证据与 C 新代码清楚分开；无实际商家验收、分发许可和 provider 选择，不标整体 goal 完成。

## 五个重点风险

1. Result 下载来自另一任务但 SKU 相同：必须 original actual/object/time/anchor 绑定。
2. 5000+1 后块和完整结果被总数隐藏：全原范围逐行结果，不截行。
3. 未知状态字符串/缺文件被推断失败：保持 unknown，禁止 retry。
4. 审核延迟与另一个操作员修改：处理成功≠原 title 生效，冲突不 overwrite。
5. worker 崩溃重启与 code switch：unknown原件优先，never resend / never silently adopt a new source。

## 当前推进记录与验收步骤

- [x] 原参考源码只读核对结果文件字段和三列，未把历史源码当本次平台实测。
- [x] C1 task scratch 15 个合成契约方法；观察缺模块 RED，以及 URL/部分计数两个实际 RED；窄 GREEN 15。代码尚未集成，不计入 B2 601 或安装包。
- [ ] 将 C1 候选与测试迁入商家版目标文件，补 native 原实例下载/证据绑定测试。
- [ ] C2 同一原任务原生只读观察/下载与不可变证据，未知只读恢复。
- [ ] C3 原 title/audit/health/portal 独立来源及完整行分类，不猜接口。
- [ ] 确认失败行子计划与新范围批准，success/unknown/awaiting-review不重投。
- [ ] Owned worker/merchant CLI execute/install.lock lifecycle 集成，崩溃和回执丢失不重传。
- [ ] 全阶段证据门禁、installed smoke及统一完整回归/包审查/私有 GitHub fresh clone验收后对应代码commit。
- [ ] 未授权的真实商家/外部付费/公开发布/商业化始终不自动执行；provider选择仍等用户。
