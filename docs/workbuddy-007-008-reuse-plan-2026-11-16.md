# WorkBuddy HD-007/008：只修适配差异，成熟能力优先

- 原有WorkBuddy HD-001、006按本轮用户提供的实机反馈记已修复；002、004部分验证，真实身份/OAuth未贯通不能冒充完成。
- 不继续扩展猜测JINGMAI_HOSTS/字段名，不保存商家payload/键路径/Cookie；恢复原jingmai-cli-linker 1.0.2的HostBrowser控制器契约，调用现有浏览器CLI/SDK。薄stdin桥接，不搬运旧app/server/shoplib（含员工开白/默认状态依赖），不改变内部安装和成熟业务代码。
- 首选已授权Profile实时复用；需要新授权时复用任务自有/已验证浏览器会话，Agent先取得可靠当前身份读取路径，控制器返回规范身份，不让用户复制ID/凭据。没有控制器明确失败，不启动旧采集器等15分钟。
- 复用原BrowserRuntime运行worker，保留psutil等官方CLI回调归属/进程收尾依赖，不用缺依赖的基础Python绕开redirector。正式reconcile兼容旧双PID，同任务证据/两者明确退出/原双锁/原件复核/未OAuth门禁保留。新进程可记录创建/父身份，旧进程不能追认父子关系。
- 小范围真实SDK/拦截页面＋标准控制器子进程＋合成官方回执，实际venv子进程与旧任务正规恢复回归。新版本0.1.3，不全量重验业务，不夹带短标题实验，不发Release或通知商家。
