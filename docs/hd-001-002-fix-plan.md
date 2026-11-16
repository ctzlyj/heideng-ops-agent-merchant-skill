# HD-001 / HD-002 最小修复计划（2026-11-16）

## 已确认与证据边界

内测报告的宿主清理机制是推测，不声称已确认Windows作业对象实现。源码可确认 auth-start --foreground 仍以Popen启动，最多等broker启动即返回；created阶段未开始OAuth，回执有先于login_process写入的authorizationStarted标记。首页URL与“直接扫码”文案不一致。waiting_login不证明完整OAuth已完成。

## 范围

1. auth-start / auth-restart / ensure-shop增加可选--wait，保持原异步用法兼容；等待不持有start.lock，输出脱敏阶段变化。新增auth-wait只等原任务，不创建新任务。命令通道须支持长运行会话，不能后台后退出包装。
2. auth-reconcile核对原launch/handle身份与进程已退出，在原worker锁内复核；不存在可靠进程证据、锁被占用、身份不一致或仅端口失联时不释放。只有明确早于OAuth的running阶段才failed可显式restart；开始过/不明阶段仍unknown不能重发。
3. worker本地保存最多64条枚举诊断事件，不写原始异常、请求、OAuth URL、凭据或页面。stdout/stderr仍不泄露SDK异常。
4. 保持首页与身份证据白名单不变，增加“如为首页先点登录，用京麦App扫码并等跳回目标工作台”说明。

## 针对性验证

模拟长命令父存活直到worker终态、worker被终止后保留原回执并正式reconcile、未知/活进程/PID复用/锁占用拒绝释放、启动缺回执/并发重新检查、progress/诊断脱敏、文案与页面一致。只运行授权模块及安装增量测试；不调用真实店铺/登录/平台、不复验成熟业务、不触碰本地短标题实验。
