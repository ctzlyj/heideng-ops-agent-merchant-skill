# POP店铺连接：Agent执行，商家只扫码

## 命令契约

由Agent用已安装Skill根目录的绝对路径执行 `python "<skill-root>/scripts/merchant.py" <command>`。下列占位符必须换成实际返回值，商家不用输入命令、Profile、Cookie、授权码或Key。

- `ensure-shop --shop-name "完整店名" [--vender-id 实际ID]`：仅复用当前商家版登记的明确目标店，实时官方核验；没有授权时不会后台启动登录，会要求前台本人扫码。
- `auth-start --shop-name "完整店名" [--vender-id 实际ID] --foreground`：商家在场、已要求连接该店时启动一次任务。自动准备商家独立公开PyPI运行时及已校验官方CLI，创建独立merchant-Profile和任务自有浏览器。未指定venderId时从本页实际响应观察，不猜接口、不把shopId当venderId。不得在安装、定时任务或无人值守时使用foreground。
- `auth-status --task-id <本次taskId>`：同任务公开状态；不启动OAuth，不输出私有URL。
- `auth-observe --task-id <本次taskId>`：公开浏览器阶段及身份响应匹配计数；不返回DOM、截图、Cookie、请求头、OAuth URL或state。
- `auth-cancel --task-id <本次taskId>`：请求原worker取消，只处理其持有的CLI进程及后代、浏览器。请求成功不是授权结果已确定；不按任意PID强杀，不碰工作浏览器。
- `auth-recover --task-id <本次taskId>`：只查询原Profile的实时官方身份并核对原目标；不重新OAuth。正在运行或尚未观察到venderId时拒绝恢复。匹配只能证明当前授权店身份，原unknown仍保留，不能称原签发已完成。
- `auth-restart --task-id <原taskId> --foreground`：仅原任务已确认failed/cancelled且从未开始OAuth时允许新尝试；重复调用同一原taskId返回同一新任务。原unknown、仍running、已开始OAuth、取消结果不明均拒绝。不是超时或网络失败的自动重试命令。

`auth-plan`只提供历史规划契约，不执行接管；商家无需自行按计划敲login命令。

## 最小执行流程

1. 明确目标完整店名；只读取商家独立shops登记，不扫描员工或其他宿主Profiles。先尝试ensure-shop。纯本地分析/素材准备不用授权。
2. 缺新授权时，商家在当前前台已要求连接，Agent执行一次auth-start --foreground。告知“请用京麦App扫新打开的任务专属网页，并完成平台本人确认”。不要打开工作浏览器已有标签或替用户做平台本人确认。
3. 保存返回taskId；每2~5秒用auth-status查询同任务，需要说明页面阶段时用auth-observe。CLI签发URL只在worker内存，确认回调监听属于本次CLI后在同一page/context导航OAuth。用户不复制URL、code或Cookie。
4. `waiting_login`需扫码；`waiting_callback_server`等自己CLI监听就绪；`waiting_oauth`需本人确认；`verifying_cli`在实时核验。`running + workerReachable=false`不是失败、未受理或安全重启的证据。不要因查不到broker/进程看似过期而重复auth-start、换Profile或换工具。
5. worker启动等待最多10秒，OAuth任务总时限900秒。过时、浏览器退出或结果不明时保留原回执；可以查询/观察/请求取消，但不能重新提交。失联时不强杀任意PID、不改回执伪造终态。只在状态改变、需扫码/确认或真正失败时通知，不刷屏。
6. 只有官方完整非mock回执、实时POP身份（完整店名/venderId/shopId/Profile）及独立店铺登记全部通过才ready。错店不登记、不执行业务。不把扫码、exit0、本地登记、mock成功或目标状态匹配说成真实签发已验收。

## 隔离和平台边界

配置在商家独立cli-home，显式JDO_CLI_HOME；每店merchant-Profile。Windows强制原生Credential Manager，不退file明文。不读取员工Key/default Profile，不用O2或内部SkillHub安装。

已审计官方0.3.7：Windows凭据通过CredWriteW写入；macOS上游用security -w secret，违反无凭据argv约束。因此当前macOS**新授权禁用**，不能绕为明文或secret命令参数；macOS安装/离线流程与已有合法授权查询另行区分。缺Chrome/Edge时明确需要系统浏览器，不操作工作浏览器、不静默下载替代浏览器。

## 当前验收等级

已完成状态机、独立浏览器adapter、公开状态broker、worker/CLI接口、跨进程去重和原任务恢复。真实SDK使用系统浏览器、全部页面请求拦截的同context导航测试已通过；真实loopback及模拟店铺worker登记已通过。**没有执行真实商家扫码、OAuth签发或店铺写入**，也不能据此宣称所有商家无感连接已验收。
