# 商家体验薄适配 Implementation Plan

**Goal:** 状态可读、恢复默认可达、长任务可理解，不新建业务规划/审批引擎。
**Architecture:** 外层只做状态投影与版本租约；原连接/OAuth/Profile和成熟回执继续是事实。长任务从原task/receipt读取，不修改生图提示词。
**Spec:** docs/merchant-experience-review-2026-11-18.md。

## 实施
- [ ] 失败测试：status/readiness与任务状态面向宿主摘要，原详细JSON保留；错误分类不再让unknown变成普通失败。
- [ ] 失败测试：同店默认恢复原任务，显式fresh才新建；多店会话不能串，连接后的Profile自动供后续任务。
- [ ] 失败测试：task/receipt汇总完成/等待审核/需本人处理/可恢复，不把pending写成完成，不新增队列。
- [ ] 失败测试：run/连接生命周期自动usage begin/heartbeat/end，detach后台更新与现有锁/快照保持。
- [ ] 文档短指南、局部离线/隔离服务验证，递增固定包，默认分支交付。真实商家业务另行内测。
