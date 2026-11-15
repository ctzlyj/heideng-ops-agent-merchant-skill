# C3 原范围实际短标题证据与后续 worker 实施细化（2026-11-16）

> 使用 executing-plans + TDD；沿现有 C/worker 计划，不扩大真实商家/模型/发布授权。

基线：`05678b6112101fb8de00059af3408462b6ba9b92`。C1/C2 同代码已完成本地和实际私有 GitHub 两组 650+7；这不是 C3 或完整 merchant execute 验收。

## 已确认与未确认来源

- 已审计官方 POP SkuShortTitle 组件声明商品详情字段 `skuList.features.shortTitle`。只读现有官方 `products/{productId}` detail；不从 skuName、长标题、模板控件、health flag 推断实际值。
- health-infos 是独立完整分页来源；分数缺失、父商品错配、坏 improvementList 不能变成“没有短标题缺项”。完整原兄弟范围保留，包括当前下架和当前缺失 SKU。
- `bossAuditStatus` 是通用采销审核，不是已确认的正式短标题审核契约。没有已确认的门户分数契约。两者明确 unknown，不猜字段/接口；完整 C3 terminal release 仍必须后续接通真实来源。
- 本阶段接通真实生产读取路径的合成测试，不调用真实 OAuth/jdo/browser/API、模型或商家写入。

## 文件职责与接口

1. `short_title_verification.py`：原生 detail 字段与健康分投影；读取前后同店身份与原商品详情 hash；原 plan/audit/兄弟范围、原 import/anchor/C2 prefix 绑定。只留字段事实与 hash，不保存原 JSON/DOM/URL。
2. `short_title_effect_state.py`：独立 append-only observation/receipt/head；核对全部原件、原 C2 prefix、原 anchors 与原完整范围；重算 flags。只从完整原件恢复确定的缺失 metadata，不能补造 observation。
3. `ShortTitleImports.collect_effects(importId, ownedBrowser)`：在同原 import 锁及真实仍持有的 install.lock witness 内先校验/恢复旧 metadata，再读当前来源并追加；历史 status/分页仅历史证据，无 current-source 宣称。
4. 门禁检查 C3 存活/孤立原件；任何 malformed 原件阻断包括 own exclusion。C3 partial 不释放写入/安装/更新/回滚；不能仅删 B2/C2 前缀后重复创建。
5. 后续确认失败子计划与 owned worker/merchant execute 仍按原计划实施；worker 必须承接 source→批准→一次 execute→原实例 observe→真实 effects 回读，不让商家手工上传，不以独立 Python API 代替最终入口。

## 任务与验证

- [ ] 迁入已 scratch RED/GREEN 的 13 字段 + 9 owned source 方法，迁入后的缺生产模块/入口 RED 必须真实观察。
- [ ] 原字段精确读取、完整原范围、双 detail/身份来源、C2/anchor prefix 绑定；partial/缺分数/错父/隐私/原件变动测试。
- [ ] durable C3 append/reconstruct、两次独立观察、不伪造 current status；unknown/混合失败与独立正式审核/门户仍 false。
- [ ] receipt/head 丢失与 bool/float/null/directory/孤立/坏 hash/坏范围/丢 B2 prefix 的 RED→GREEN；门禁 own/其他工具/安装覆盖。
- [ ] 安装后新 smoke 与同原任务一次 upload/create→结果→effects；独立有界 review 后才允许私有代码提交。
- [ ] C3/确认失败子计划/worker 全阶段集成后统一完整回归、脱敏包、私有 GitHub 全新安装，不每个微小内部函数重复 650 全套。

Ruling: 正式短标题审核与门户来源未确认时保持 unknown，但继续实现已具备证据的实际 title/health 读取与持久 worker — 避免编造接口，也不把 partial 永久当最终交付 — 成本是完整 terminal release 暂不可开启。
Ruling: C3 observation 显式绑定当时 C2 prefix 和已存在 anchor 子集；后续合法新观察不使历史原件失效，删除任一被引用原件仍 fail closed — 成本是必须逐次核验历史 prefix，不能只信一个可改 head。
