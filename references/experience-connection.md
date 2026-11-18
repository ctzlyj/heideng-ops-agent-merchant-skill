# 连接店铺与复用授权

## 适用问题与需要的事实

商家报店名/简称/venderId，需要找店、复用现有授权、首次授权或排障。先确认商家要操作的店；shopId 与 venderId 不能混用。多店匹配返回 ambiguous 时问具体哪一家，不选默认店。

需要本商家独立 CLI 和状态目录、成熟连接器返回的 Profile，以及实时 venderId/shopId/shopName。所有店铺模块可共享这次已核验身份；模块切换不是重新扫码理由。

## 判断与建议路径

- 通常先 `run connection -- ensure-shop --shop "目标店铺" --no-auth`。登记别名/多个Profile只用于定位，最终以实时 venderinfo 核验为准。
- 已有授权可用则直接复用；本地显示过期不代表不可用，官方可能自动刷新。网络/权限错误不能一律当授权失效；先按实际错误排障。
- 确实需新授权，沿用用户针对本店的明确许可，原 ensure-shop 去掉 --no-auth；商家本人在同一隔离浏览器页自行选择密码、短信或扫码，宿主衔接官方 OAuth。不要另建授权系统，不复制Cookie/Token。
- `awaiting_auth` 是等待宿主处理，不是授权失败。按原 jobId、当前 browser-action 操作并回报真实上下文/身份，返回 callback_unknown 时先核对同一Profile，不能再扫一轮制造重复任务。
- 网页后续任务需要真实商家持久 profileDir。用原连接器保存的 browserProfileDir，在同店匹配后交给 POP 原导入；不猜用户工作浏览器目录。

路径可由宿主已有浏览器工具完成。包装器没有某个宿主操作入口并不禁止宿主处理原 HostBrowser 动作；配置/报告必须是实际拥有的上下文，不能凭标签存在填 owned/isolation/身份。

## 工具与完成证据

- `scripts/merchant.py run connection -- ensure-shop|resolve|wait|verify|doctor ...`，由Agent补原命令实际参数。
- 真实 HostBrowser 契约：[原适配器](../mature/connection/app/browser_adapters.py)；可选私有输送：[browser_bridge](../mature/connection/scripts/browser_bridge.py)。
- 完成：实时正确店铺身份、可用专用Profile和官方凭据原管理结果。网页登录成功或本地连接命令启动不等于 ready。
- 用户未交办业务：完成连接后不自动发布、采集、改价或付费生成。

## 来源、例外和限制

整理自 jingmai-cli-linker 1.0.2 / 1c438fc；[原用法](../mature/connection/references/usage.md)、[浏览器会话](../mature/connection/references/browser-session.md)。原文个人目录/固定服务端口是源版本背景，商家路径/实际端口以本包环境为准，见 [环境](merchant-cli-environment.md)。
真实商家新授权与各宿主实机没有本次实测结论；这是环境证据限制，不是长期禁止未来授权。官方权限或宿主浏览器能力缺失时报告具体缺项，不借员工身份。


## 0.4.2 连接执行路径（本地适配，不替代真实验收）

- 首次连接由宿主先 `ensure-shop --no-auth`；已有ready直接结束，不启动连接服务。确需本店新授权时去掉no-auth，保留awaiting_auth的jobId/Profile。
- 本包提供 `scripts/host_connection_controller.py`。宿主在任务目录用准备好的runtime解释器运行它作为browser_bridge的controller argv，不再自己编写CDP服务、OAuth确认脚本或Profile登记补丁。`python scripts/merchant.py run --entry scripts/browser_bridge.py connection -- --controller '<该argv JSON>' --once --timeout 20`。普通observe没有回报时继续观察原任务；导航/确认未明时先核对，不能重复点击。
- 控制器只使用商家state/browser-profiles的持久目录和同contextId。登录页为passport.shop.jd.com/login/index.action；不替商家选择扫码/密码/短信，不复制Cookie。商家本人处理登录/风控；认证魔方明确去京东商城App完成安全验证，后台不继续发新授权。
- 同店普通重试不会返回旧failed job。需要原Profile/页面恢复时用ensure-shop --resume，它先核验已有结果；不擅自cancel，不把result_unknown改为未提交。连接服务用脱离CLI进程组方式启动，宿主结束单条命令不等于结束授权。
- OAuth确认只用于当前已许可范围；额外权限/费用/挑战交还本人。控制器只回报非敏感页面身份与context/profile元数据；最终ready仍以官方Profile实时venderinfo核店。
- 这是必要的WorkBuddy/宿主适配。真实京麦登录、账号风控、OAuth与各宿主进程回收仍需实际设备内测，不能把控制器本地测试称为真实商家授权通过。


## 单命令连接（替代0.4.2手工循环主路径）

新店已获用户明确授权后，宿主只调用 `ensure-shop --shop <目标> --timeout 600`，不传 `--no-open`。默认provider=builtin，由原BrowserAuthJob直接驱动包内HostConnectionController；宿主不再循环browser_bridge、拼controller argv或常驻临时控制器。老店`--no-auth` ready不会打开浏览器。

浏览器默认跟随本机Chrome/Edge设置，之后绑定同店context/profile/channel。登录页交给商家选择密码/短信/扫码，文本店名不是完整身份；只从已登录工作台读取可靠店铺信息，最终仍以官方venderinfo核店。遇到账号风控只提示本人操作，不重开任务。

0.4.2手工`browser_bridge`入口保留给需要自带HostBrowser的宿主，不是默认新店路径。页面驱动随动作释放，商家profile保留，不能反复打开新窗口。OAuth确认最多一次；超时只观察/核验，不重复点击。

## 0.4.5 现场反馈适配

- 新店默认仍是单命令 `ensure-shop`。工作台只有店名、没有 DOM venderId 时，店名匹配只用于进入官方 OAuth；最终 ready 仍须官方 Profile 实时返回匹配的店名与数字 venderId，不能用文本店名代替完整核店。
- 返回中的 `browserChannel` 是实际通道，`browserSelectionReason=system-default-https` 表示跟随系统默认浏览器，`reused-shop-session` 表示复用同店隔离会话。Edge/Chrome 不是串号依据；商家登录方式始终由本人选择。
- `/api/job` 丢失会明确返回 `job_lost`，同店再次 `ensure-shop` 默认恢复；已取消任务新建同店 worker，不假装原线程仍存活。多店会话目录和 Profile 不混用。
- 控制器 `--help` / `--describe-contract` 不需要商家状态目录。Key 的 Tk 回退页会输出不含 session/CSRF 的本机根地址；不得把带令牌的输入 URL、Key 或 Cookie 写入日志/回复。

## 0.4.6 授权进程生命周期（必须遵守）

- 新店默认只执行 `run connection -- ensure-shop --shop <目标> --timeout 600`。builtin 在**当前命令进程内**运行既有连接服务并等待完整授权窗口；`waiting_browser` 是内置控制器正在打开页面，不是让宿主接管。
- 不要在这条默认路径里另跑 `jdo-cli login --no-browser`、手工拼 OAuth URL、`Start-Process msedge/chrome`、用 `present_files` 展示链接，或让商家复制链接。上述绕法曾直接造成窗口不可见和商家放弃授权。
- 商家仍在隔离的京麦登录页自行选择密码/短信/扫码；登录后由原 BrowserAuthJob 导航官方 OAuth、处理当前范围确认并实时核店。日常浏览器 Cookie 不复制，宿主内嵌面板不可操作时不得假称已代点。
- 老店 ready 在只读解析阶段直接返回，不启动嵌入服务。需要新授权才启动；显式 `--no-wait`、自带 HostBrowser/`--browser-config` 保留原高级路径，但宿主必须真正拥有并持续驱动该会话。
- `job` 或 `wait` 返回 `job_lost` 表示原服务任务已经不在，不能继续声称“窗口开着/任务活着”。同店再次 `ensure-shop` 默认恢复；禁止改成手工 OAuth 或跨店新任务。
- 黑色控制台、外部窗口是否可见属于真实宿主/Windows 会话证据，未实机看到窗口前不得汇报“已打开”。前台生命周期修复不代替真实商家可见性验收。
