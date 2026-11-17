# 浏览器会话适配与 Agent 内部桥接

实际提供默认 HostBrowser 与可选独立 Chromium Playwright。当前不固定 WebCLI/JoyCode 为唯一依赖，也不声称已在真实京麦上验证所有宿主。

## HostBrowser

Agent 使用本次宿主可用的浏览器路由。先确认任务会话的归属和 context；复用已有会话还要确认目标店。普通 tabId 不是 Cookie 隔离证明。

以本机服务自己的会话认证访问私有 `/api/browser-action`，得到 `{jobId, action:{id,kind,target/url}}`。只用于工具内部受控导航，不打印、截图、写普通日志。OAuth 地址不出现在 `/api/job` 或公开命令输出中。

| kind | 浏览器操作 |
|---|---|
| open_login | 定位/打开京麦网页；target 是店名或 venderId 字符串 |
| observe | 返回登录状态、可靠身份和平台 challenge |
| open_oauth | 已证明的同 context 内导航本轮官方地址，不复制 Cookie |
| confirm | 处理当前已授权范围的正常确认；新增权限/收费或本人验证时停住 |
| close | 只关闭本任务打开的页面 |

回报到私有 `/api/browser-report`：

```json
{
  "jobId": "本任务标识",
  "actionId": "本轮动作标识",
  "result": {
    "contextId": "宿主证据确认的实际会话标识",
    "owned": true,
    "isolated": true,
    "loggedIn": true,
    "identity": {"shopName": "真实店名", "venderId": "真实商家ID", "shopId": "真实店铺ID"},
    "challenge": ""
  }
}
```

首次回报需 contextId、owned=true，并有 isolated=true 或已验证复用的 verifiedReuse=true；后续必须同 contextId。字段必须来自工具实测证据，不能编造，也不让用户填写。

Host 确认回报保留受限的 challenge，流程会提示平台本人步骤。取消后仅匹配当前任务的 close 动作可报告，其余迟到动作仍拒绝。控制台没有浏览器消费者时显示 waiting_browser 和“接管当前连接”入口，不误报扫码页已打开；点击复制连接目标是用户操作，不由后台改剪贴板。

重复轮询同动作先查是否已执行，不重复导航/确认；报告只消费一次，旧动作、重复、不同任务或 context 被拒绝。取消中断本任务等待，超时保留浏览器登录态。

身份由当前工具读已经验证的页面接口或可靠 DOM，只回报店名、venderId、shopId。读不到可靠身份时让用户完成平台店铺选择或继续调查页面，不猜接口、不读 Cookie/历史、不提取授权码。真实 JoyCode 内置工具的 context 证明与跨域 SSO 尚未单独验收。

Agent 可运行 `scripts/merchant.py run --entry scripts/browser_bridge.py connection -- --controller '<JSON argv>' --once --timeout 20`，通过 stdin 把私有动作交给已选定的任务局部浏览器控制器。地址不放进命令参数、普通 stdout 或日志；控制器只返回观察结果。桥接助手沿用 linker 当前服务连接和本机认证，不写死宿主端口或凭据。用户不需敲命令或配置控制器，Agent 按实时可用工具选择。

助手在用户状态目录保存最小 jobId/actionId/phase 回执；重复调用不会重做结果未知的同动作。超时或报告不明先核对动作/任务状态，`consumed` 不等于浏览器成功或授权 ready，不能据此声称完成；最终以指定 Profile 实时身份核验为准。收到 ready 后处理本任务 close 动作，仅关闭自己的页面。

## 可选 Playwright

Agent 可给 ensure-shop 提供 `--browser-config <配置文件>`，指定 provider=playwright。先观察实际页面后提供经验证的 identityScript、identityScriptVerified=true，脚本只返回 `{loggedIn,identity,challenge}`。没有证据就继续其它可用宿主路径。

配置支持 loginUrl、明确授权按钮 confirmSelector、headless、timeout。真人扫码用任务专属可见窗口；本地模拟用 headless。HTTP 仅允许环回模拟页面，真实导航用 HTTPS。默认新建独立 context；userDataDir 只接受明确归属及已验证复用身份，还要现场核验，不自动复制工作配置。

登录、OAuth、确认使用同 context；账号变更、验证码、确认按钮缺失时停止自动确认。模拟证明 Cookie 由浏览器自然携带，没有读取或导出。真实京麦跨域 SSO 未验证。

Playwright 对象和收尾在创建它的工作线程操作。只关闭本任务页面；其它页面由其主人处理。


### 商家版内置控制器与迟到动作

WorkBuddy等宿主可使用包内`scripts/host_connection_controller.py`的argv，不需要再编写CDP控制脚本。它持久化contextId、owned profileDir与browserChannel，不持久化URL、Cookie或身份凭据。打开京麦商家登录页后由商家选择登录方式；认证魔方给出去京东App完成安全验证的明确动作。

导航/确认有独立pending阶段，迟到不等于失败；允许同一actionId的迟到回报以完成核对，不新建动作重放。observe是无限等待中的读取轮次，空闲不会杀死授权。普通同店重试创建新任务，显式resume才恢复原任务/Profile；OAuth未知结果仍先核同一Profile。
