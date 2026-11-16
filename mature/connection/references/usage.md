# 使用说明与排障

## 架构

Skill 自带一个只监听 127.0.0.1:8765 的本机服务（app/server.py）。授权由官方 `jdo-cli login --no-browser` 完成：
它自己监听 127.0.0.1:9001 回调、校验 state、用内置授权应用换取令牌并存入 Windows 凭据管理器。
1.0.2 默认先京麦网页登录扫码和身份核验，再由同浏览器会话衔接官方 OAuth，最后 venderinfo 核验登记。用户只报店名，用京麦 App 扫码，不敲命令、不复制凭据或填写 Profile。

- app/shoplib.py：店铺解析、登记、体检、环境检查、专用浏览器查找（纯本机）。
- app/server.py：本机服务与授权任务。
- scripts/linker.py：命令行入口。
- app/browser_auth.py / browser_adapters.py：阶段控制与 HostBrowser / 可选 Playwright；见 browser-session.md。

扫码与回调分开计时；命令默认最多等 3 秒后返回 awaiting_auth/stage，不占住整个 Agent 会话。job/wait 短轮询同一 jobId；结果未知先核验本任务 Profile。--resume 恢复时先核对已有结果，新的 OAuth 由官方生成新 state，旧报告/回调不得重复处理。

## resolve 的匹配顺序

1. 本机登记表（`%USERPROFILE%\.jingmai-cli-linker\shops.json`）：店名、别名、venderId、shopId。
2. 登记里没有 → 对本机全部 Profile 实时只读调用 venderinfo（并行），补全登记后再匹配。
3. 命中后再实时核验一次：身份与登记不符 → `mismatch`；调用失败按错误类型分流。

店名匹配先精确（忽略大小写、空格、标点），再包含匹配，所以简称可用；多家命中返回 `ambiguous`。
同一 venderId 的多个 Profile 视为同一家店，按 `primary`、合法名称、最近核验选一个。

## 错误类型

| errorKind | 含义 | 处理 |
|---|---|---|
| auth_missing | Profile 缺授权配置 | 重新授权（ensure-shop 自动处理） |
| auth_expired | refresh_token 失效 | 重新授权 |
| permission | 权限不足 | 核对开白登记表 |
| network | 网络/超时 | 稍后重试；不当作未授权 |
| no_cli | 没有 jdo-cli | `doctor --install-jdo` |
| port_busy | 9001 被占用 | 查看归属；只取消本任务拥有的 PID，不关闭其它任务 |
| auth_busy | 已有授权在进行 | 完成或 `cancel` |
| credential_isolation | 官方槽未证明对应 venderId | 保留回执，不迁共享 default，不注销其它店 |
| identity_unverified | 缺可靠网页登录身份来源 | Agent 核对页面接口/DOM，或使用其它可用适配器 |
| callback_unknown | 回调丢失/结果不明 | 先核验任务 Profile，不重复授权 |

## 不要用本地到期时间判断是否重新授权

本地 status 显示的到期时间会过期，但 jdo-cli 调用时会用 refresh_token 自动续期，实测仍成功。只认实时 venderinfo。

## 1.0.0 授权启动即 NameError（已在 1.0.1 修复）

现象：未授权店铺执行 `ensure-shop` 时授权任务启动失败，报 `NameError: name 'CALLBACK_PORT' is not defined`；已授权店铺的复用不受影响。
根因：`app/server.py` 中一行注释末尾带了字面的反引号加 `n`（PowerShell 转义残留），把下一行 `CALLBACK_PORT = ...` 吞进注释。
验证：`tests/test_shoplib.py::test_server_module_constants_defined` 与 `test_login_job_start_reaches_port_check`；在 1.0.0 的 server.py 上这两条会失败。
教训：发布前必须在**新代码的新服务进程**上跑一次授权启动路径，不能只靠 `ready` 的复用结果；改动代码文件时用 Python 写入而不是 PowerShell 字符串替换。

## 升级后卡在「已收到京东授权，正在校验店铺身份…」

现象：授权页停在 127.0.0.1:9001 的“已收到京东授权…正在校验店铺身份…”，命令一直等不到结果。
根因：升级前常驻的旧版本服务仍占着 8765，新命令调用的是旧代码（旧版自己监听 9001，页面文字即其产物）。
处理：linker 通过 `/api/health` 比对新行为版本 2.1.0。只有身份明确且支持安全退出的空闲本连接器可请求 shutdown；在途授权或不同目录服务不停止。更老服务不支持安全退出时保留并明确说明，由原任务结束后再启动新代码，不按 python 进程名强杀。
验证：`python -m pytest tests -q`（test_stale_server_version_is_replaced）。

## 技术要点（踩过的坑）

- 历史旧路径曾用共享 `:default` 后缀再迁移。1.0.2 先确认网页登录 venderId，再用任务自有 Profile 与该 venderId 授权；官方回执槽须明确对应目标。共享 default 槽不盲目迁移，不注销已有凭据；不能用 Profile 名称推断 Token 隔离。
- `jdo-cli login` 会改全局 default_profile，服务在登录前后保存并恢复。
- JSON 必须 UTF-8 无 BOM。
- 名称以 `-` 开头的 Profile 要写成 `--profile=NAME` 才能传参。
- 全新 `init` 的默认 endpoint 是 localhost:8080，服务显式使用 `https://mcp-open.jd.com`。
- venderinfo 店名为 data.shopBaseInfo.shopName，公司名为 data.venderBaseInfo.companyName；venderId 必须明确来自 data.venderId，不能用 shopId 替代。
- win32com 在非主线程使用需 CoInitialize；PyInstaller 打包需 `--hidden-import win32com.client --hidden-import pythoncom`。

## 店铺专用浏览器

现有快捷方式可给 Agent 提供归属线索，不是新用户前置条件。须验证同 context 和店铺身份，不能只启动一个普通标签就当隔离。实际默认 HostBrowser/可选 Playwright 接入见 browser-session.md；shortcut 仍可生成已授权店铺的本机入口。

## 官方 CLI 安装与版本

`doctor --install-jdo` 只在本机没有 jdo-cli 时执行：

1. 匿名读取京麦官方版本信息（https://mcp-open.jd.com/cli/version-policy.json），取 windows-x64 的安装包路径和校验值。
2. 下载安装包，校验值与官方信息一致才继续，不一致立即停止，不安装任何东西。
3. 解压到临时文件再原子替换到 `%USERPROFILE%\.jdo-cli\bin\jdo-cli.exe`；失败保留原状、清理临时文件。
4. 安装成功后自动 `init`，并提示下一步 `ensure-shop`。

不碰 `profiles`、`credentials`、`config.json` 里已有的内容。失败时给同事看的是「问题 / 影响 / 下一步」三句人话，`detail` 字段只供排障。
本 Skill 不内置 CLI，也不再从其他 Skill 的内置包取旧版本。只支持 Windows x64，其他平台会明确提示不支持。

版本显示（`doctor` 的 jdo-cli 检查项）：`current` / `latest` / `minSupported`。`needsUpdate` 只在低于官方下限时为真；
`behindLatest` 仅表示不是最新，不要求操作。升级用官方命令 `jdo-cli update self`，本 Skill 不自己覆盖 exe。

## 测试

    python -m pytest tests -q

## 安全边界

- 只监听 127.0.0.1。
- 不读取、不返回、不记录 token、appSecret、cookie；不把任何密钥写进代码、文档或发布包。
- 不修改全局默认 Profile。
- 不用于商品发布、改价、库存或营销报名。
- 原始 CLI 输出只在内存解析并脱敏，普通 job/命令输出没有 OAuth/state/code 或完整 log。
- 真实京麦扫码、跨域 SSO 与真实签发未在本次升级中执行；本地模拟不是线上授权成功。
