# 连接店铺与复用授权

## 适用问题与需要的事实

“昨天连的店怎么少了”先看 `shop-locations [--shop <店名或编号>]` 返回的安装位置和登记记录。若宿主已持有同一商家明确选定的旧安装，可传 `--other-install <旧安装目录>` 校验其绑定。历史 WorkBuddy 专家提示用其原有入口查询。随后从所属安装通过 `run connection -- audit --no-write` 或指定 Profile 只读核店。报告须说明查的是哪个安装和哪种连接。要求“合并”时先统一展示来源，不搬运 Cookie、CLI 授权文件、系统凭据或手改 proof。只清理快捷方式的授权不包含删除旧安装和商家任务目录。

### macOS ARM64 的原授权与本机环境

商家说“继续上次”而同名记录有歧义时，宿主从已核对的原连接回执取 `query`、`profile` 和 `jobId`。用 `run connection -- ensure-shop --shop <原 query> --resume --profile <原 Profile> --job-id <原 jobId>` 只读对账。商家无需记编号。没有匹配的原任务时，按实际店铺身份消歧。

安装器复核京麦正式归档列出的文件。遇到配套文件缺失、内容改变或 Mac 主程序丢失执行权限时，重新安装会在新的程序目录恢复官方内容，原店铺状态和个人文件继续保留。Mac 正常连接遇到官方程序缺文件错误时，宿主可直接从返回的 `officialCliCheck` 查看同一程序的无账号公开查询结果，并沿原任务对账。

- 优先用原来绑定的商家状态尝试 `run connection -- ensure-shop --shop <店名> --no-auth`。同名空记录若仍可能对应在途授权或另一家店，会保留待核状态。只有同店实时身份明确才报告 `ready`。
- 商家说“继续上次”时，宿主从已有回执取店铺原称、Profile 和 jobId。同名查询返回的 `originalReceipt` 也可提供这三项，依据是同一目录中该原称的已暂停任务及其官方完成记录。执行 `run connection -- ensure-shop --shop <原称> --profile <原 Profile> --resume --job-id <原 jobId>` 核对该笔任务。商家单独交办店名时仍按同名候选判断。
- 京麦 0.3.7 的“已授权”回执和新 OAuth 回执有不同的字段。新版用原 Profile、原 CLI home 的官方状态和实时核店来恢复。Mac 上官方仍使用该 Profile 自身的默认凭据槽时，经核验可继续复用；证据不够则保留原回执。宿主无需打开钥匙串、导出 Token 或复制凭据文件。
- 运行文件带 iCloud 占位标记时，让商家在访达下载回执指出的路径，再继续原任务。不要因读取卡住另建空状态。若安装器本身尚未下载，先在访达下载源码目录。
- 权限弹窗、浏览器无法启动和官方 CLI 的 HTTPS 错误要按实际阶段排查。用 `run connection -- browser-check` 可检查本机隔离浏览器。用 `python scripts/merchant.py --state <原目录> doctor-cli` 检查已校验的官方二进制能否启动并访问京东公开版本服务。后者使用临时 CLI home，不发起店铺登录，结果包含版本、哈希、失败阶段和脱敏原因。该探测成功后仍要以原任务的官方核店结果判断授权。

商家报店名/简称/venderId，需要找店、复用现有授权、首次授权或排障。先确认商家要操作的店；shopId 与 venderId 不能混用。多店匹配返回 ambiguous 时问具体哪一家，不选默认店。

需要本商家独立 CLI 和状态目录、成熟连接器返回的 Profile，以及实时 venderId/shopId/shopName。所有店铺模块可共享这次已核验身份；模块切换不是重新扫码理由。

## 判断与建议路径

商家用简称，随后指出对应的官方店名或商家 ID 时，核店成功后用 `run connection -- remember-alias --shop <官方店名或venderId> --alias <商家叫法>` 记录这次明确对应关系。新对话直接以简称做只读解析。若简称指向两家店，只问一次能区分两家的问题。相同主体、相似名字和默认 Profile 均不足以选店。

- 通常先 `run connection -- ensure-shop --shop "目标店铺" --no-auth`。登记别名/多个Profile只用于定位，最终以实时 venderinfo 核验为准。
- 已授权店铺的 `ready` 证明这次官方只读核店通过；`webLoginStatus=not-checked` 表示本次没有查看网页登录状态。商家交办补建该店的工作台或入口时，使用 `run connection -- ensure-browser --shop <官方全名或商家ID> --profile <原店 Profile>`。商家指定 Chrome 或 Edge 时加 `--channel chrome` 或 `--channel msedge`。不同浏览器使用各自的商家专用资料，已有官方授权可直接沿用。
- 宿主读取原命令的进度事件。商家说“扫好了”，页面仍在等待时，执行 `run connection -- login-completed --job-id <事件里的 web-jobId>`，原任务会在自己的登录页检查一次工作台。网页核店成功看 `webLoginVerified`、页面查验时间和 `desktopShortcut.path`。显示其他店、没有可区分的店铺 ID、资料被占用或回执冲突时，以具体状态交付。先前已验明的资料可用 `shortcut` 补回桌面文件。
- 确实需新授权，沿用用户针对本店的明确许可，原 ensure-shop 去掉 --no-auth；商家本人在同一隔离浏览器页自行选择密码、短信或扫码，宿主衔接官方 OAuth。不要另建授权系统，不复制Cookie/Token。
- `awaiting_auth` 只有在原会话确实仍运行时才表示等待，不是授权失败；默认builtin由包内流程驱动，不交给宿主手拼OAuth。按原 jobId、当前 browser-action 操作并回报真实上下文/身份，返回 callback_unknown 时先核对同一Profile，不能再扫一轮制造重复任务。
- 网页后续任务需要真实商家持久 profileDir。用原连接器保存的 browserProfileDir，在同店匹配后交给 POP 原导入；不猜用户工作浏览器目录。
- 连接达到 `ready` 后，黑灯用本店的浏览器和持久资料创建桌面快捷方式。商家交办连接已经包含这一步。把 `desktopShortcut.path` 返回的实际位置交给商家，状态为 `unavailable` 时说明具体原因。商家反馈找不到时，沿同店 `shortcut` 回执核对系统桌面和文件是否仍在。只读的 `--no-auth` 探测保持只读。

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

- 首次连接由宿主先 `ensure-shop --no-auth`。已有 `ready` 时复用授权，明确交办连接时补齐桌面入口。确需本店新授权时去掉 `--no-auth`，保留 `awaiting_auth` 的 jobId 和 Profile。
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

- 新店默认只执行 `run connection -- ensure-shop --shop <目标> --timeout 600`。builtin 在**当前命令进程内**运行既有连接服务；登录和OAuth共用本次有界连接预算；`waiting_browser` 是内置控制器正在打开页面，不是让宿主接管。
- 不要在这条默认路径里另跑 `jdo-cli login --no-browser`、手工拼 OAuth URL、`Start-Process msedge/chrome`、用 `present_files` 展示链接，或让商家复制链接。上述绕法曾直接造成窗口不可见和商家放弃授权。
- 商家仍在隔离的京麦登录页自行选择密码/短信/扫码；登录后由原 BrowserAuthJob 导航官方 OAuth、处理当前范围确认并实时核店。日常浏览器 Cookie 不复制，宿主内嵌面板不可操作时不得假称已代点。
- 老店 ready 在只读解析阶段直接返回，不启动嵌入服务。需要新授权才启动；显式 `--no-wait`、自带 HostBrowser/`--browser-config` 保留原高级路径，但宿主必须真正拥有并持续驱动该会话。
- `job` 或 `wait` 返回 `job_lost` 表示原服务任务已经不在，不能继续声称“窗口开着/任务活着”。同店再次 `ensure-shop` 默认恢复；禁止改成手工 OAuth 或跨店新任务。
- 黑色控制台、外部窗口是否可见属于真实宿主/Windows 会话证据，未实机看到窗口前不得汇报“已打开”。前台生命周期修复不代替真实商家可见性验收。

## 审计后的连接返回契约（0.4.7代码候选）

- `--timeout` 是本次登录+OAuth的共用预算，不是每个阶段各加一轮时间。阶段变化输出 `connection-progress` JSON事件（jobId/Profile/阶段/实际通道/剩余预算）；不输出OAuth URL、验证码、Token或页面全文。开页事件只是正在打开，不证明商家可见。
- 超时或用户结束等待，原worker停止并核对原Profile，收尾本任务回调和浏览器上下文后再关嵌入服务。`paused/processRunning=false` 明确没有后台继续；持久浏览器Profile与pending回执保留，下一次同店ensure-shop先核对原结果。收尾未确认时返回阻塞，不能称已关闭或重发。
- 最终 `ready`/`mismatch`/`cancelled`/失败与 `paused` 分开。只有官方完整核店才ready。ID-only新店请求中，可靠工作台店名仅证明登录会话存在，可以衔接本次OAuth；原期望venderId不改、不由DOM猜ID，最终官方ID不匹配仍拒绝登记。
- 同店暂停的callback_unknown优先核验原Profile；未核实则保留暂停，不启动新OAuth。不同店空ID不视为匹配，不串用pending或Profile。
- 以上为代码/离线契约修复；真实WorkBuddy可见窗口、商家登录→OAuth→ready仍须另外获得授权后验证。

## 口述名称与宿主误用（g9jb现场）

- 口述别名未登记、页面官方名不同，返回 mismatch 时按 expectedShopName 和 actual 向商家确认是否为同店。确认后，用原口述名称执行 `ensure-shop --shop <原名称> --resume --confirmed-shop-name <官方名称>`。此入口沿用原店铺浏览器资料，以官方名称核店后登记原口述别名。回调结果未知时先核对原授权。
- 内置Playwright直接持有BrowserContext/Page，不以人为打开TCP调试端口为前置。缺少--remote-debugging-port不能直接诊断“控制器看不到”，不能据此改走手工OAuth。可见页面和登录检测的失败应看真实阶段/错误，不读Cookie/History来猜。
- jdo-cli直调必须使用商家隔离环境；不同HOME写出的Profile不是包装器的同一份Profile。禁止cp日常HOME Profile或手改authorization-proof.json作为恢复。修复应复用原待核对回执与正确隔离入口。
- venderinfo的productCount不是商品盘点成功证据；是否有商品以原商品/SKU分页完整性核验为准，不能据0就让商家重新上架。


## 0.4.9：已登录识别、原凭据槽与收尾

- 扫码期间，内置连接器只观察商家专用窗口中已有的页面。二维码过期、网络异常或切换网络后，沿原任务观察，采用京东页面给出的刷新或安全验证提示。宿主根据实际页面和网络反馈说明原因。
- 商家主动告知“登录好了”而进度仍是 `waiting_login` 时，宿主调用 `run connection -- login-completed --job-id <原任务ID>`。同一个活动任务最多在当前登录页访问一次工作台，再等真实店名渲染。返回 `workspace_check_requested` 只表示原任务收到请求。随后读取原任务的 `wait` 回执。真正的官方店名与口述别名有差异时按上面的店名确认流程继续。
- 工作台店名只用来衔接原官方 OAuth。晚出现的 venderId 仍由官方只读核店证明；官方 CLI 本任务的 `:default` 凭据槽只允许在**原 Profile 命名空间、原商家 JDO_HOME**内定位到该数字 ID。要有本任务真实完成/保存/非模拟元数据，并再次核店；原回执缺保存/模拟布尔字段时，只读核对本 Profile 的官方 status 元数据，不猜字段值。首次核店断网前保存原 native 完成标记；网络恢复仅原 jobId、原 Profile 文件、原真实完成记录可恢复槽位并再次核店，没有完成证明的未知授权不重提。不是借全局 default Profile、跨 Profile 复制授权或手改证明的恢复方法。
- 明确 rejected 的失败试连 Profile 保留原文件和审计记录，但不作为可用同店候选；真实不同 venderId 仍按原歧义规则处理，网络失败/未知 Profile 不能随意忽略。
- `ready` 与 `resourceCleanup` 分开：本地浏览器关闭确认无需已经消失的活 contextId；仅已核店、worker 已停止时才可保留 ready 并报告清理待核对。worker 仍活着或回调未知，仍不能声称资源已关闭、后台仍运行或重新发起授权。
- 以上有离线回归和真实 Playwright/Edge 的拦截页面验证，**不是**真实 WorkBuddy 可见窗口、扫码/OAuth、老店免扫码复用的商家验收。
