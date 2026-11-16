# 商家任务浏览器配置（薄传输，业务规则仍来自原采集器）

Agent 通过实际宿主的任务浏览器/已核验复用会话提供状态目录下 browser_context.json，不让商家写脚本或复制Cookie。
保留原 session、tab(32位targetId)、idleTimeout(>=7200)、windowMode=background、probeSku(当前可访问源SKU)。
仅增加实际工具观察的 contextId、owned=true、isolated=true 或 verifiedReuse=true、cdpEndpoint=本次环回CDP。新隔离浏览器 profileDir 必须在商家 browser-profiles/ 下；已核验复用会话不复制原浏览器资料。

包内默认 owned_cdp_transport 仅实现原 Page 网络/页面控制契约，使用已迁入的成熟诊断 Cdp；不实现签名或价格SDK，不加载公司模块。
页面自身 PSign/SHA256/getJsToken、X-Skuid-Param/x-sdx/soaRate 只在原页面/进程内存复用；捕获数据通过原 project/validate 白名单落盘。
adapter拒绝关闭非本次创建的页面，因此原批次扫描所有item标签的清理不能误伤工作页；无法证明归属的旧页不自动关闭。

调用原脚本：run --entry scripts/collect_signed.mjs collection -- --root <本次输出> --run <原参数>；点击备用及批量驱动同样使用已注册原文件，不再需填写 wcli main/page/preload 或员工安装目录。
如需额外宿主传输，Agent只使用已审阅的显式适配器，不能悄悄回内网工具/员工SSO。当前独立Chromium/CDP本地拦截测试不代表真实JD登录态或所有宿主已验证。
