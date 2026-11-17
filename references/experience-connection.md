# 连接店铺与复用授权

## 适用问题与需要的事实

商家报店名/简称/venderId，需要找店、复用现有授权、首次授权或排障。先确认商家要操作的店；shopId 与 venderId 不能混用。多店匹配返回 ambiguous 时问具体哪一家，不选默认店。

需要本商家独立 CLI 和状态目录、成熟连接器返回的 Profile，以及实时 venderId/shopId/shopName。所有店铺模块可共享这次已核验身份；模块切换不是重新扫码理由。

## 判断与建议路径

- 通常先 `run connection -- ensure-shop --shop "目标店铺" --no-auth`。登记别名/多个Profile只用于定位，最终以实时 venderinfo 核验为准。
- 已有授权可用则直接复用；本地显示过期不代表不可用，官方可能自动刷新。网络/权限错误不能一律当授权失效；先按实际错误排障。
- 确实需新授权，沿用用户针对本店的明确许可，原 ensure-shop 去掉 --no-auth；本人京麦 App 扫码，宿主在同一隔离浏览器会话衔接官方 OAuth。不要另建授权系统，不复制Cookie/Token。
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
