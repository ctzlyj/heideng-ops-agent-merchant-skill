# POP店铺连接：Agent执行，商家只扫码

## 命令契约

由Agent用已安装Skill根目录的绝对路径执行 `python "<skill-root>/scripts/merchant.py" <command>`。下列占位符必须换成实际返回值，商家不用输入命令、Profile、Cookie、授权码或Key。

- `ensure-shop --shop-name "完整店名" [--vender-id 实际ID]`：仅复用当前商家版登记的明确目标店，实时官方核验；没有授权时不会后台启动登录，会要求前台本人扫码。
- `auth-start --shop-name "完整店名" [--vender-id 实际ID] --foreground [--wait] [--wait-timeout 960]`：商家在场、已要求连接该店时启动一次任务。自动准备商家独立公开PyPI运行时及已校验官方CLI，创建独立merchant-Profile和任务自有浏览器。未指定venderId时从本页实际响应观察，不猜接口、不把shopId当venderId。不得在安装、定时任务或无人值守时使用foreground。foreground表示商家在场，不意味着命令一直存活；WorkBuddy等退出命令会清理子进程的宿主必须同时使用--wait。等待不持有全局启动锁，只有阶段变化才输出脱敏JSON进度，最后一行是返回结果；调用工具须支持长运行/同一会话等待，不能启动后另起短命令再退出原包装。
- `auth-status --task-id <本次taskId>`：同任务公开状态；不启动OAuth，不输出私有URL。
- `auth-observe --task-id <本次taskId>`：公开浏览器阶段及身份响应匹配计数；不返回DOM、截图、Cookie、请求头、OAuth URL或state。
- `auth-cancel --task-id <本次taskId>`：请求原worker取消，只处理其持有的CLI进程及后代、浏览器。请求成功不是授权结果已确定；不按任意PID强杀，不碰工作浏览器。
- `auth-recover --task-id <本次taskId>`：只查询原Profile的实时官方身份并核对原目标；不重新OAuth。正在运行或尚未观察到venderId时拒绝恢复。匹配只能证明当前授权店身份，原unknown仍保留，不能称原签发已完成。
- `auth-restart --task-id <原taskId> --foreground`：仅原任务已确认failed/cancelled且从未开始OAuth时允许新尝试；重复调用同一原taskId返回同一新任务。原unknown、仍running、已开始OAuth、取消结果不明均拒绝。不是超时或网络失败的自动重试命令。

`auth-plan`只提供历史规划契约，不执行接管；商家无需自行按计划敲login命令。

- `auth-wait --task-id <原taskId> [--wait-timeout 960]`：只等待原任务，不重新启动worker/OAuth。仅适用于worker仍活着的原任务；不能复活已被宿主杀死的子进程。若命令超时/被中断，返回waitTimedOut/waitInterrupted，不代表授权失败或可重发。
- `auth-reconcile --task-id <原taskId>`：正式核对“worker退出、回执仍running”。需原launch/handle任务和PID一致、OS确认进程已退出、原worker锁可持有，并在锁内复核。仅created/starting_worker/initializing_worker/waiting_login且无authorizationStarted/authorizationOutcomeUnknown/cleanupIncomplete时写入failed与safeToRestart=true；之后可明确执行auth-restart --foreground --wait。授权已开始或阶段不明则unknown，禁止再发OAuth。端口失联、活进程、权限不足、缺launch、PID复用或锁占用都不放行；不强杀、不手改回执、不删targets登记。

## WorkBuddy 内测旧死任务的更新顺序

1. 若任务当前仍在waiting_login/waiting_oauth且worker可达，保留原长命令与浏览器，先完成或通过原worker取消，不能任务中换代码。
2. 真正硬退出的旧0.1.0任务会挡住安装；先将新0.1.1源码下载到独立临时目录，校验来源。从**下载的源码**运行merchant.py，保持原--home/HEIDENG_MERCHANT_HOME，用auth-reconcile核对反馈中的原taskId。该命令不安装、启动登录或查询真实店铺。
3. 只有safeToRestart=true的原任务才恢复成失败；所有阻塞原任务核对后再按标准install.py更新，保留原任务/cli-home/店铺资料。不要删任务或解除未知状态来绕更新门禁。0.1.1避免same-version-different-artifact。
4. 更新后由Agent执行auth-restart --task-id <原taskId> --foreground --wait，用户在场完成登录；把同一长运行命令保持到终态。宿主若没有长会话能力，明确报告宿主限制，不反复启动。

## 平台先检查

进入扫码前先核对平台支持（onboarding的shopCapability），不支持时在任务记录/运行时下载之前返回明确原因。Windows x64可用；macOS arm64有二进制但当前凭据实现被安全门禁阻断；macOS x86_64没有本地官方构建。不能继续承诺扫码连接或先下载浏览器后失败。详见references/install-runtime.md；本体安装和离线任务仍可用。

## 最小执行流程

1. 明确目标完整店名；只读取商家独立shops登记，不扫描员工或其他宿主Profiles。先尝试ensure-shop。纯本地分析/素材准备不用授权。
2. 缺新授权时，商家在当前前台已要求连接，Agent执行一次auth-start --foreground。告知“请在本次任务窗口完成登录；如显示京麦首页，先点击登录，再用京麦App扫码，等待返回目标店工作台”。保持本次page/context，不复制passport Cookie；身份证据仍来自登录后工作台响应，不扩宽到passport。不要打开工作浏览器已有标签或替用户做平台本人确认。
3. 保存返回taskId；--wait模式会自动报告阶段变化，Agent只等待同一工具会话；异步模式才每2~5秒用auth-status查询同任务，需要说明页面阶段时用auth-observe。CLI签发URL只在worker内存，确认回调监听属于本次CLI后在同一page/context导航OAuth。用户不复制URL、code或Cookie。
4. `waiting_login`需先确认页面：京麦首页先点登录，passport页扫码，然后等返回目标工作台；`waiting_callback_server`等自己CLI监听就绪；`waiting_oauth`需本人确认；`verifying_cli`在实时核验。`running + workerReachable=false`不是失败、未受理或安全重启的证据。不要因查不到broker/进程看似过期而重复auth-start、换Profile或换工具。只有auth-reconcile的严格退出与未开始OAuth核对成功才允许显式restart。
5. 异步worker启动等待最多10秒，OAuth任务总时限900秒；--wait默认960秒、可设0~1800秒，等待过时不自动取消或重启。过时、浏览器退出或结果不明时保留原回执；可以查询/观察/请求取消，但不能重新提交。失联时不强杀任意PID、不改回执伪造终态。只在状态改变、需扫码/确认或真正失败时通知，不刷屏。
6. 只有官方完整非mock回执、实时POP身份（完整店名/venderId/shopId/Profile）及独立店铺登记全部通过才ready。错店不登记、不执行业务。不把扫码、exit0、本地登记、mock成功或目标状态匹配说成真实签发已验收。

## 隔离和平台边界

配置在商家独立cli-home，显式JDO_CLI_HOME；每店merchant-Profile。Windows强制原生Credential Manager，不退file明文。不读取员工Key/default Profile，不用O2或内部SkillHub安装。

已审计官方0.3.7：Windows凭据通过CredWriteW写入；macOS上游用security -w secret，违反无凭据argv约束。且invoke/status等已有授权查询也可能自动刷新token并写Keychain，因此当前macOS**所有带凭据CLI执行禁用（含新授权和已有授权查询）**，不能绕为明文或secret命令参数；公开工具下载、文档校验、商家版安装及离线准备仍可使用，等待上游提供无secret argv凭据实现后再开放。缺Chrome/Edge时明确需要系统浏览器，不操作工作浏览器、不静默下载替代浏览器。

## 最小诊断（HD-001）

本地auth/events/<taskId>.json保存最多64条枚举事件：taskId、time、event、stage、status、authorizationStarted。只在阶段变化/worker启动、收尾、恢复时记录，不保存SDK原始stdout/stderr、页面、异常正文、Cookie或OAuth URL。日志是辅助诊断，不是授权成功或安全重启的依据；日志写入失败不改变业务状态。stdout/stderr继续不导出可能含敏感信息的SDK流。

## 当前验收等级

已完成状态机、独立浏览器adapter、公开状态broker、worker/CLI接口、跨进程去重和原任务恢复。真实SDK使用系统浏览器、全部页面请求拦截的同context导航测试已通过；真实loopback及模拟店铺worker登记已通过。**没有执行真实商家扫码、OAuth签发或店铺写入**，也不能据此宣称所有商家无感连接已验收。

0.1.1已补HD-001/HD-002针对性离线与真实子进程生命周期测试：同命令等待、硬退出、持锁复核及安全重启；没有运行真实WorkBuddy扫码/OAuth，需内测商家复测。
