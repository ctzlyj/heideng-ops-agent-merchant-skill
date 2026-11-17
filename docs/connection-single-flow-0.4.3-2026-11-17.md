# 0.4.3 单命令连接修复

## 根因
0.4.2只把临时CDP脚本换为包内controller，却继续要求宿主循环browser_bridge；BrowserAuthJob默认provider仍是host，真实主链没有自动执行它。另有登录页文本猜店铺身份、默认Chrome覆盖浏览器选择、包装器隔离HOME校验profile等问题。

## 修复
默认新授权选择builtin，由原连接器直接驱动包内控制器。老店ready零浏览器。controller跟随系统Chrome/Edge并绑定目标店铺profile，显式使用真实商家状态目录；登录页不推断店铺身份，官方venderinfo仍最终核店。OAuth只确认一次，pending/unknown不重复点击。原HostBrowser/bridge保留给自定义宿主，不再是商家主路径。

公开京麦登录页已用本控制器在隔离profile打开，标题正确，未登录不误报；关闭自有页面与驱动，无真实账号、OAuth或店铺写入。生图提示词未改。

## 验证边界
本地联合测试、公开页面与固定源更新只证明适配。未独立取得本轮WorkBuddy建议全文：分享页跳到登录，接口invalid_token；未把该事实说成读完。实际WorkBuddy登录/OAuth/风控仍需要用户安排实机，不宣称真实商家连接已通过。
