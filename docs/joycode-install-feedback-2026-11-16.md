# JoyCode安装反馈处理（2026-11-16）

原报告来自0.1.0 / 31ae5c5；本轮累积优化推送到开发分支，不通知内测商家更新，不将本轮改动宣布正式发行。

| 原问题编号 | 判断 | 处理与限制 |
|---|---|---|
| HD-2026-11-16-001 | 安装映射缺陷 | joycode默认改为.joycode/skills，保留显式目录及universal；未证实全部JoyCode版本是否同时扫描.agents。旧目录不自动迁移/删除；文件校验与宿主识别分开。 |
| HD-2026-11-16-002 | 上游平台缺项 + 商家版前置提示不足 | 只读核对官方version-policy，stable0.3.7发布清单只包含windows-x64/macos-arm64，无macOS x86_64。macOS arm64凭据安全限制保持；auth-start在浏览器运行时/任务创建前拦截，onboarding明确平台不支持而不引导扫码。仍未解决macOS真实店铺链路。 |
| HD-2026-11-16-003 | 可选组件失败误报整体失败 | Skill安装实际结果保留；officialCli失败分开返回unavailable/ready/reason和warning。核心安装失败仍blocked；已有校验CLI刷新失败不隐藏其可用性。不发布原始异常内容。 |
| HD-2026-11-16-004 | 环境前置缺失与指引缺口 | 新增install-runtime.md：复用宿主Python、无包管理器时独立可信便携CPython、同发行校验哈希与安全解压、后续固定使用准确解释器。不新增自制bootstrap，不替换系统Python；macOS运行时下载未实测。 |

官方策略来源：https://mcp-open.jd.com/cli/version-policy.json。未调查或承诺官方Intel Mac发行计划，未联系上游或商家。

本地针对性验证：安装宿主路径、可选组件平台/网络/敏感异常失败、真实文件安装校验、核心包校验失败、macOS提前拦截和上手提示，以及现有授权/安装回归。没有真实商家授权、真实生图、macOS实机或JoyCode扫描行为验证。

下一轮统一更新时应使用新版本号，避免同版本不同包；这批修复同步开发分支，当前不重建已交付安装包或发布新Release；统一更新时使用新版本号。不修改内部采销版或本地短标题实验内容。
