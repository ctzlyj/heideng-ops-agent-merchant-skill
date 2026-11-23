# WorkBuddy 授权联调

0.4.19 是授权接入联调版本。完整商品运营专家等待京麦依赖；当前构建回执 `readyForSubmission` 为 false。已有 0.4.18 的名单和商家状态可用于联调。

专家清单在 `.codebuddy-plugin/plugin.json` 引用根目录的 `.mcp.json`。其中的 `heideng-member` 通过标准 stdio 启动包内 Python 工具，以 `x-workbuddy.auth.type=token` 和 `tokenSchema` 声明专用 Key。WorkBuddy 向该工具进程注入表单值。工具验证本批名单和 LTS4AI 资格，仅在对应的生图子进程临时传递 Key。原生费用确认窗口只用于已交办任务的预算决策。

在仓库根目录运行以下命令可构建预览或联调包。真实名册只在仓库外使用，每项为一把高熵专用 Key 的 SHA-256 指纹。
```text
python scripts/build_workbuddy_expert.py --preview --output dist/expert-preview.zip
python scripts/build_workbuddy_expert.py --integration-only --invite-digests <指纹名册.json> --publisher-email <联系邮箱> --output dist/expert-auth-integration.zip
```

联调包应在真实 WorkBuddy 中观察召唤前的凭证卡、字段注入、重启后的复用、缺失和失效凭证及断开连接。离线协议测试只能证明声明与本机程序的字段和调用路径相通。专家包内的内核保留正常来源审计与原始说明，专家自身加载专用经验导航。对外部京麦的操作在联调入口关闭，京麦本机授权不会由此包发起。

完整版本恢复送审前，应取得平台认可的京麦授权路径。如果采用 marketplace 连接器，取得已上架 source 后在 `dependencies.connectors` 声明，证明它产生的当前店铺授权能被同一台设备、同一商家状态内的业务工具消费，再联通核店、续用和断开。WorkBuddy 的 CLI 连接器检查清单要求覆盖 macOS 与 Linux 及 auth/status/unAuth；目前京东官方 0.3.7 二进制发行清单仅列 Windows x64 和 macOS ARM。先与平台确认现有连接器、独立连接器的平台范围，或官方支持的其他等效方案。

[专家依赖声明](https://open.workbuddy.cn/docs/expert#声明方式) · [连接器规范](https://open.workbuddy.cn/docs/connector) · [京东 CLI 发行清单](https://mcp-open.jd.com/cli/version-policy.json)
