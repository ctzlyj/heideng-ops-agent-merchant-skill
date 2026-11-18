# 0.4.6 前台单命令授权 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 WorkBuddy 中连接服务被命令回收、job null 和宿主绕道手工 OAuth 导致的授权失败。

**Architecture:** 默认 builtin `ensure-shop` 在当前命令进程内嵌入既有 HTTP 连接服务，等待完整超时；显式 `--no-wait` / HostBrowser 保留原路径。复用既有 BrowserAuthJob、OAuth 和官方核店，不新增授权系统。

**Spec:** 0.4.5 商家完整 WorkBuddy 对话（20 条主消息、201 次工具调用）中 #142 ensure-shop、#149 connect、#151 job null 及后续不可见窗口/复制链接证据。

## Constraints

- 不读取或复用凭据，不执行真实扫码、店铺写入或付费生成。
- 不手工构造 OAuth URL，不复制 Cookie，不让宿主默认 Start-Process/present_files 代替内置连接。
- 保持多店 Profile 隔离和同店恢复；只修改连接适配、经验文档和局部测试。

### Task 1: 前台服务生命周期与状态

- [x] 写默认等待不被 3 秒截断、嵌入服务可启动/关闭、job null 明确 `job_lost` 的失败测试。
- [x] 写 builtin 不再提示宿主接管、默认超时 600 秒的失败测试。
- [x] 最小实现 server factory、linker 前台包装及默认提示。
- [x] 运行连接/单流程/体验全套局部测试。

### Task 2: 经验纠偏与 0.4.6 发布

- [ ] 文档禁止默认手工 jdo OAuth、Start-Process 或复制链接，明确前台命令等待与恢复。
- [ ] 运行完整离线套件和 release consistency，更新 provenance 与实施记录。
- [ ] 使用 publish_stable 递增 0.4.6，验证固定包和私有下载后提交推送；不通知商家。
