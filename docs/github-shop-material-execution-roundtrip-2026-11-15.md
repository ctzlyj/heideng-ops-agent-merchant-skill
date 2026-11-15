# 私有GitHub整店素材执行往返（2026-11-15）

实际克隆 ctzlyj/heideng-ops-agent-merchant-skill / codex/merchant-foundation，固定已测试代码 `7fd656b97bd6ef65411ffc82fb785b587fcc67f9`，非本地复制验收。

- 新HOME、新venv、公开PyPI测试依赖、真实安装与onboarding。
- 重建归档SHA256 `15e0ffa703a699708fee947f6cdd2202ffcf098c90b8f776ec0c0a37aa782265`，与本地最终包相同；81文件含manifest，受审计包无个人路径、凭据模式或未知文件。
- 完整隔离 **497测试** 和 **15安装/官方源码边界smokes** 全部通过。每stage实际尝试保留在JSON，不把retry/resume说首次通过。
- 两个视频smoke首次在公开PyPI解码运行时安装步骤报incomplete；失败原件保留。同一clone/commit/归档仅续跑失败及未跑阶段，成功阶段不重跑；两个视频smoke串行重跑原完整断言，以诊断runner原样委托subprocess捕获安全输出，不改变源代码、源地址、版本、超时、费用边界或断言。该续跑不表述为首次全绿。 原安全包装将OSError/超时合并为incomplete，首次底层具体异常未保留，因此不把串行通过当成“并发根因已证实”或源码修复。续跑依赖实际退出码/耗时的无路径摘要保存在JSON。
- 新整店安装smoke实际使用已安装根/子合同、原件状态、CLI与更新门禁：53SKU商品50+3、另一3SKU商品；统一根批准、离线兄弟不写、原字段保留；第2块unknown不推进/重提；本店原图片上传回执跨2商品复用；默认完整余缺和分页。
- 测试后detached clone干净，重建包哈希一致。之后主分支只追加本验证证据，不改变此代码包。

新整店smoke为合成商家/原生API/图片技术预检，旧媒体smokes实际公开解码依赖和合成视频，不能替代真实视觉/商业质量。无真实OAuth、当前认证卡、店铺写入、消息或付费模型；平台审核/信息分刷新未证明。

本地25方法与3项审查发现及同一lost-proof残余的主复现/修复/独立窄复核见 shop-material-execution-verification-2026-11-15.md/json。内部1.5.4 / 13692b759bd52e35c3670cf8fad5330e1bf2b576未改；视频上游审计0.3.0 / 29548089f7b71ac77ddb584caac0966a98df24ab。

驳回/空槽修复、短标题、远端既有视频采纳、跨版本旧未执行计划安全重建、真实商家/多类目/大SKU验收、生成服务及分发/商业许可仍未完成。整体goal保持active，私有交付不是正式上线或收费批准。
