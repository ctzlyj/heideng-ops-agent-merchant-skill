# C3 部分原生来源与持久化证据研发记录（2026-11-16）

## 结论与范围

私有代码 `03e7fd94162369289500106223b442b876c67b1d` 新增实际短标题/health 字段原生读取、完整原兄弟范围及独立 observation/receipt/head。**不是完整 C3、merchant execute 自动链路上线、真实商家验收或公共发布**。正式短标题审核、完整材料 health/门户、确认失败子计划和持续 owned worker 仍必须实现。C1/C2 的历史 650+7 双环境验收不冒充本次全套验收。

本次真正执行：**70 项定向方法（38 项新方法＋32 项受影响旧回归）**，181.050 秒，0 failure/error/skip；代码/test hash 在原进程中不变。新 HOME 安装 smoke 从 installed 模块调用原生 API，合成上传/创建各一次，原 5 个兄弟 SKU 全保留，历史与当前来源分离，缺 receipt 从完整原件恢复，新 C2 prefix 不覆盖旧 C3；pending 不重投。

包 **107 文件（106 源文件＋manifest）**，SHA256 `8b77fb12f9ea47544d9aee4e0d8760c3a4642c553edf205d14bbc4ae2c6e0e56`；包审查 personalPaths/credentialPatterns/unknownFiles 均 0。**688 项仅核对发现数量，尚未全套执行；本阶段没有重新执行 GitHub fresh clone。** 为避免每个内部函数重复长全套，统一全回归/实际 GitHub 安装留作 C3/worker 整体集成最终门禁，当前只交私有研发阶段代码。

## 独立审查与真实修复

独立审查指出 2 个 Important，主实现者用 2 方法/3 实际失败复现后修复，再通过 2 方法 GREEN。新独立复核 **5 方法/12 cases**，27.375 秒，0 failure/error；13 个源/测试/参考 hash 与当前一致。

1. 尚无 B2 attempt 但已有 nonterminal C3 observation 时，原门禁错误返回空闲：现其他同店写入及 native/full update 都阻断；只保留经过自己原件核对的精确原 coordinator 排除。
2. native detail/health/identity 或 append 前丢失 browser/原 install witness 时，原来仍追加“当前已核验”原件：现每个来源边界及追加/发布前核对原 witness，不补拿锁。独立 8 种失锁/关闭场景均拒绝，未追加新观察，B2/C2 原件不变。

旧 87-method 候选验证因上述独立＋自有真实失败证明 snapshot 不安全而停止，原句柄终态 -1、部分日志保留，**不称 87 通过，也不是因等待超时重启**。Windows 测试 harness 的 Popen-lambda 破坏 asyncio 子类导入曾导致测试前错误，根因确认后仅修正 scratch harness 为拒绝启动的 class，未削弱业务断言。

## 安全与未完成

只使用合成 shop/profile/browser factory/DNS/HTTP/template/approval；未启动真实 browser 或 jdo/OAuth/API、商家写入、模型、消息。实际值只读 `skuList[].features.shortTitle`，不从长标题/health flag/模板推断。两次 detail hash 和同店身份不是服务端事务或 CAS；未知/缺分数/缺行不缩范围。历史 effects/status 带观察时间，不冒充刚读取。

通用 bossAuditStatus 不是正式短标题审核证明。formalAuditVerified、portalVerified、整体 healthVerified、imported、retryAuthorized 仍 false。partial C3 不释放门禁；新确认失败子计划、worker 与真实授权/类目/规模验收不能用 API/导出文件替代。

内部仍 **1.5.4/13692b759bd52e35c3670cf8fad5330e1bf2b576**、clean、未修改。视频仅记录已审计 **0.3.0/29548089f7b71ac77ddb584caac0966a98df24ab**，不称最新；图片/视频来源待用户选择，分发及商用许可未获自动批准。整体 goal active。

## 下一步

按现有 C/worker 计划接通持续 merchant execute：同一 owner/runtime/install.lock 完成 source→root→明确批准→一次上传/创建→原实例结果→实际回读；关闭/崩溃/未知只沿原件恢复。再实现确认失败专属修复、独立正式审核/完整 health/门户及完整 terminal 门禁，最后统一全套、包审核、私有 GitHub fresh clone 和真实商家单独授权验收。
