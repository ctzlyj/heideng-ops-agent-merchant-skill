# OAuth 接管开发验收（2026-11-15）

这是商家版本次增量开发的证据，不是内部版历史验收，也不是商家真实授权或线上业务验收。目标仍在实施中。

## 实现范围

- auth_flow：单提交状态机，网页精确身份后才启动官方OAuth；完整非mock回执、实时POP核验和商家登记才ready。
- auth_browser：任务自有非持久context与同一page，京麦扫码后同上下文OAuth；身份来自实际xhr/fetch JSON，不猜身份接口；不导出DOM/截图/请求头/存储状态。
- auth_runtime：按需从公开PyPI准备独立venv（仅playwright/psutil），不读公司Key/代理/员工HOME；记录来源、版本、wheel元数据。当前wheel安装经pip公开源完成，不能把元数据列表冒称对全部已安装文件逐字节验证。
- auth_manager/broker/worker：独立后台worker、loopback随机port公开状态/观察/取消、Host/Origin/header约束；同目标幂等，跨进程复用原任务；状态失联不换Profile重启。
- official：显式JDO_CLI_HOME与merchant-Profile，Windows原生凭据后端不退file；回调只检查自己持有进程树的监听，不用空TCP探测、不杀其他任务。
- 恢复只查原Profile，目标匹配仍保留原unknown；只有从未开始OAuth的明确终态才能显式auth-restart，且对原taskId幂等。

## 已观察的 RED → GREEN

1. browser adapter缺模块 → 两项同context/私有URL测试通过。
2. 非JSON/空/list/不完整CLI输出被当failed、list导致AttributeError → 全部保留unknown，不重启OAuth。
3. 浏览器poll失败遗留本次CLI → 所持Popen与可证明后代清理，旁路进程不受影响。
4. clean env移除ProgramFiles导致Playwright找不到系统浏览器 → 保留系统安装路径字段，员工Key和个人LOCALAPPDATA仍隔离；真实SDK测试通过。
5. recovery在验证taskId前创建锁文件导致路径逃逸 → 先校验原任务及safe_join，无旁路文件。
6. 同店名不同venderId可并行启动 → 对活动/unknown目标冲突拒绝，原任务不重提。
7. worker启动broker失败留下running → 持有锁后落初始化阶段并保存明确失败，原回执不重放。
8. 新授权spawn结果不明被当failed → 预先保存authorizationStarted，失败保持unknown。
9. URL允许非443端口/控制符/过大私有状态 → URL严格拒绝；stderr行与内存队列有界。

## 实际验证与边界

- 独立公开PyPI运行时真实安装：playwright 1.65.2、psutil 7.2.2。不是旧环境包存在即通过。
- `tests/smoke_auth_browser.py`：真实SDK/系统浏览器/headless；全部页面请求由route拦截，仅合成店铺与合成Cookie；验证网络响应身份、同page/context、Cookie上下文保留、OAuth state不发布、自有资源关闭。不是京麦/OAuth真实签发，route拦截也不是OS级网络防火墙。
- `tests/smoke_auth_process.py`：真实子进程/loopback，两个外部进程复用同一任务，仅一个worker；mock店铺完成登记；跨Origin取消403，合法本地取消受理。没有真实店铺API调用。
- 官方公开策略0.3.7的deprecated Python源按策略SHA核验后仅内存静态审计。Windows用CredWriteW；macOS用security -w secret，确有凭据argv风险，因此新授权已禁macOS。不可将原生Keychain等同于无argv凭据。
- 内部只读参考仍为1.5.4 / 13692b759bd52e35c3670cf8fad5330e1bf2b576，Git工作区未改。
- 指定视频上游HEAD仍为29548089f7b71ac77ddb584caac0966a98df24ab / 0.3.0，未激活原Skill，生成来源待用户补充。

## 尚未验收与下一步

没有真实商家扫码、OAuth签发、店铺写入、付费生成。浏览器失联/worker异常退出缺可证明终态时仍保守保留原回执，不自动重启。macOS新授权需官方无secret argv方案，不能偷偷降为明文。继续官方高层商品/价格/素材适配、完整发行安装回测及许可审核；不把本检查点称为整体目标完成。

## 独立评审修正

有界只读代码评审发现并由本地回归复现了：登记前ready、两个布尔值冒充完整回执、陈旧port跨任务取消、父进程退出后已证明后代遗留、worker丢失restartOf。7项新增回归（含清理不完整不得ready）先失败后修复。现按照已核验官方源码的真实command/profile/cliVersion/timestamp、tokenMocked=false、授权阶段和保存成功字段验收；登记完成及所持资源清理后才发布ready；所有broker请求在动作前绑定taskId，取消回执再核对；已证明psutil句柄缓存保留，PID复用不用于追杀。真实性仍是mock/SDK等级，不是商家签发实测。

安装还新增了Python -I隔离模式回归：原installer因脚本路径被隔离而ModuleNotFoundError，现显式加入自身模块根路径；干净HOME从校验ZIP安装、onboarding、未前台auth-start在依赖安装前拦截已验证。浏览器测试临时HOME及测试生成缓存留在忽略的agent-work内，不进入提交或安装包。

Skill压力测试基线没有违反不重复授权原则，但缺命令参数导致无法自主继续。更新连接参考后的有界测试能准确查询/取消原任务、保留unknown、区分目标当前身份与原签发、对明确未开始授权的取消使用幂等restart。不是实际店铺或权限测试。
