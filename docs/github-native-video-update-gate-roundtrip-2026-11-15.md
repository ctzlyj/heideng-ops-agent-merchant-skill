# 私有 GitHub 原生视频更新门禁往返（2026-11-15）

已实际克隆私有仓库 ctzlyj/heideng-ops-agent-merchant-skill，分支 codex/merchant-foundation，固定代码提交 `6e4dedc1784bca4f97a9db04befe0107d191b41c`，非仅本地复制或缓存验收。

- 新 HOME、新 venv、仅公开 PyPI 测试依赖；重建归档 SHA256 `e6a7158aab8139530de9bbadd329b3721e9800e0df9faf3a666a470f515ececd`，与本地主流程一致。
- 归档审核 77 文件（含 manifest），无受审计包个人路径、凭据模式或未知文件。
- 新 HOME 实际安装和 onboarding；完整隔离 **472 测试**、**14 安装/官方源边界 smoke** 均通过。配套 JSON 保留每个 stage 的实际尝试，不覆盖超时/失败事实。
- 新更新门禁 smoke 在实际已安装商家模块上完成本地升级/回滚和 unknown 恢复现场保留，明确取消未尝试计划、旧模块/旧计划拒绝写入、新进程按0.2.0合成升级包重建计划后可合成执行；0.2.0不是正式发行。
- 测试后 detached clone 干净，重建哈希相同。之后主分支只追加本往返证据，不改变已测试的源代码包。

新 gate smoke 技术预检/店铺/API/上传均为合成；旧独立 media smoke 实际安装公开解码依赖并解码合成视频。无真实商家 OAuth、API 写入、上传、平台审核、消息或付费模型调用。内部参考1.5.4 / 13692b759bd52e35c3670cf8fad5330e1bf2b576未改；视频上游审计0.3.0 / 29548089f7b71ac77ddb584caac0966a98df24ab。

23项门禁专项和4项审查发现的主复现/修复/独立窄复核见 native-video-update-gate-verification-2026-11-15.md/json。整店执行、驳回修复/短标题、远端既有视频采纳、真实商家验收、生成服务方案及对外分发权利仍未完成。整体 goal 保持 active，私有代码交付不等于正式上线或获准收费。
