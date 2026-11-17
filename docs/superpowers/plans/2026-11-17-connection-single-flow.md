# 单命令连接主链 Implementation Plan

**Goal:** 0.4.2把控制器交给宿主循环仍未形成产品；改为包内单一连接流程，宿主Agent只发起目标和处理本人步骤。
**Architecture:** 原连接器仍是身份/OAuth唯一来源；其HostBrowser由本包内置浏览器控制器驱动，不再把controller argv/循环作为商家主路径。无公司依赖、无Cookie导出。

## 必改根因
- `HostBrowser`长轮询但无消费者，要求Agent循环 → 默认内置worker或成熟provider直接执行。
- `HostConnectionController`按body猜shopName，不含venderId/shopId，且未进入工作台 → 只能观察页面阶段，最终身份仍官方CLI；不得以店名猜测loggedIn。
- 浏览器单会话跨店、Chrome与Edge profile类型、同店恢复绑定。
- 不把长超时/忽略测试当完成；实际京麦/OAuth仍需用户安排真实验收。
- 生图提示词、成熟店铺身份校验、未知OAuth回执保护保持。

## 实施
- [ ] 失败测试：ensure-shop默认自动驱动包内控制器，无需browser_bridge循环；ready老店不启动浏览器。
- [ ] 失败测试：无真实店铺身份不得loggedIn；风险页给本人指引；OAuth确认仅显式用户已授权范围。
- [ ] 失败测试：controller会话绑定目标店铺/Profile，不能新任务复用别店登录态；不混浏览器类型。
- [ ] 隔离本机端到端：原Job+内置控制器+官方身份fixture完成等待；无真实登录。
- [ ] 经验页改为一个自然语言目标，必要局部验证，递增固定包、签名及默认分支。
