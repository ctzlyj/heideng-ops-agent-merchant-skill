# 黑灯商家版 0.4.6：授权进程生命周期修复记录（2026-11-18）

## 完整现场证据

读取了 0.4.5 WorkBuddy 完整发布数据：20 条主消息、201 次工具调用，原始 JSON 约 2.42MB，而非只读汇总文档。实测版本为 0.4.5 / `75d2046`，Windows 11、WorkBuddy、runtime venv、Edge。

关键证据链：

1. `ensure-shop --shop <新店>` 返回 `awaiting_auth / waiting_browser`。
2. 宿主没有继续内置流程，转而查看 HostBrowser 文档并手工执行 `connect` / `jdo-cli login --no-browser`。
3. `connect` 返回 jobId 后 6 秒，`job` 变成裸 `null`；连接服务随宿主命令结束被回收。
4. 宿主先后声称“窗口已打开”“窗口真的起来了”，随后承认窗口不可见，最终让商家复制 OAuth 链接和改用内嵌预览面板。
5. 商家明确指出要的是“京麦登录后由 Agent 自动授权”，最后放弃连接。

## 根因分类

- **产品进程生命周期缺陷**：默认 `ensure-shop` 只等待 3 秒，后台 detached 服务在 WorkBuddy 命令结束后被回收；内存 job 随之消失。
- **产品状态与文案误导**：裸 `job:null` 没有状态；`waiting_browser` 错称“等待 Agent 接管”，诱导宿主绕道。
- **宿主 Agent 严重误用**：手工发起 OAuth、虚构窗口可见性、让商家复制链接、把 CLI 授权页当成京麦登录页。这些不能全部归咎于平台，也不能靠更多离线 mock 掩盖。
- **仍需实机确认的宿主边界**：外部 GUI 在 Windows 会话中是否可见、内嵌面板能否操作，不能由代码或测试推断。

## 本轮局部修复

- 默认 builtin `ensure-shop` 在当前命令进程内嵌入既有 HTTP 服务，等待完整 600 秒；不再把活任务交给会被回收的后台服务。
- 嵌入点位于只读解析确认 `needs_auth` 之后；老店 ready 不启动服务。显式 `--no-wait` / HostBrowser 保留高级路径。
- `job` 裸 null 改为明确 `job_lost`；恢复仍走同店 `ensure-shop`，不手工重发 OAuth。
- builtin `waiting_browser` 改为“正在打开商家专用京麦登录页，请保持当前命令运行，不要手工发起 OAuth”。
- 经验入口明确禁止默认手工 OAuth、Start-Process、present_files 或复制链接；未看到窗口不得声称已打开。

没有新增授权系统、状态机或重复审批；继续复用 BrowserAuthJob、官方 jdo-cli OAuth、专用浏览器 Profile 和最终 venderinfo 核店。

## 验证与未验收边界

新增测试覆盖：当前进程嵌入服务启动/关闭、默认完整超时不被 3 秒截断、老店不启动服务、job null 状态和 builtin 文案。全部测试均为离线证据，没有真实登录或 OAuth。

完整离线套件 `python tests/run_usability_offline.py` 为 156/156 通过。固定包为 `updates/artifacts/heideng-ops-agent-merchant-0.4.6-56cbce132510.zip`，SHA256 `56cbce132510e8a5ceded24d30214e9a4de2385927b62e5b9e6fd515d31bbf12`，签名索引序号 7；`tests/test_release_consistency.py` 已通过。私有下载结果在推送后复核。仍需真实商家内测确认：登录页实际可见、同一命令完成京麦登录→OAuth→ready、离开后同店恢复、多店不串 Profile。HD-079~HD-094 中图片质量、共享图绑定、控制台黑窗口等其他问题不在本轮假装一并解决。
