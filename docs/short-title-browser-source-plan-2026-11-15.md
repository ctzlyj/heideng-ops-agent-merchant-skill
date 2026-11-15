# 短标题B1浏览器原件实施计划（2026-11-15）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task; test-driven-development and verification-before-completion apply.

**Goal:** 实现任务自有浏览器读取当次同店身份、短标题抽屉任务页及真实下载模板，并冻结到独立原件，供B2/C继续使用；不是上传执行完工。
**Architecture:** 独立标准库协议核对 + 现有BrowserRuntime可承载的Playwright browser adapter。原ShortTitlePlans及完整审计核对前后库存；每会话只能用商家状态内生成的profile，不能接入任意已有profile。
**Tech Stack:** Python标准库，按需公开Playwright，合成factory测试，不访问真实网页。
**Spec:** docs/short-title-import-design-2026-11-15.md，B/C约束仍完整有效。

## Global Constraints

只合成店铺、响应、DOM、模板和身份；不运行真实jdo info/OAuth、商家网页或写入、付费模型、消息、公开发布。内部/个人Skill只读，不迁移缓存xlsx或Cookie。源和错误只保存非私密摘要/哈希；不保存原DOM/JSON/签名URL。B1不生成写入批准，不暴露可绕过B2的execute入口。

## Review Focus

拆分对象拼身份、旧响应冒新来源、别的页面/错误origin/任务ID、模板入口或下载歧义、任意profile或关闭失败后复用、原计划/模板/库存篡改。

### Task 1: 当次浏览器源与安全传输
Files: heideng_merchant/short_title_browser_contract.py、short_title_browser.py；tests/test_short_title_browser.py。
Interfaces: ShortTitleSourceBrowser(state,client,plan_id,*,session_id=None,factory=None,clock=None,channel=None,headless=False).open()/poll()/capture()/close()。合成factory只用于测试，生产通过公开Playwright。open建立任务自有persistent_context，capture只操作原抽屉的唯一模板link和queryByPage响应；不上传/创建任务。
- [ ] RED：模块缺失及同店完整对象/当次新响应/独立profile/精确source URL/任务类型非实例/抽屉唯一入口/下载匹配、体积/不安全模板/脱敏/关闭失败测试。
- [ ] 实现、GREEN：原件中只有来源哈希和公开明确字段；下载文件名由Agent生成，不采用远端suggested_filename。无法确认POP类型/模板link/任务结构时具体拒绝，不猜平台值。
Expected: focused unittest所有持久方法通过，0真实网络/业务写入。

### Task 2: 独立原件冻结及安装回归
Files: 同上；references/native-short-title-browser-source.md；tests/smoke_short_title_browser.py。
Interfaces: capture保存sourceId/sessionId/原planFingerprint/同店/当次网络原件哈希及templateSha/解析核对，status()只历史核对，不能称当前身份/导入/全任务列表完整。read_source(state,client,source_id)拒绝错文件名、源hash/模板篡改、profile owner丢失/隔离失效。未完成的浏览器资源不标记closed，也不释放为可重开。
- [ ] RED→GREEN：原库存前后漂移不留可用source、source/模板篡改、重复capture不覆写、错误会话/原计划不采纳。
- [ ] 有界独立review，主复现任何Important，验证之后私有代码交付；新HOME安装新smoke及原短标题/整店/更新门禁回归；全套/包审计/GitHub验收证据另存。
Expected: source-captured不等于approval-ready/imported；B2/C保持未完成。

## Pre-flight rulings

Task1→Task2：当次network proof不是写许可；source记录绑定完整原plan/审计，Task2校验后也只能读。queryByPage只有已观察一页，未验证平台分页schema，不冒称完整任务目录或以缺少ID证明没有任务。下载link文字/结构仅从当前drawer唯一匹配，实际平台不匹配时停止，不用内部缓存兜底。POP仅接受显式POP字符串；数字类型需要后续授权现场的确切契约，不照旧代码猜。

当前项目和分支按用户要求复用；不另建工作区/用户聊天。A1/A2代码与验收分别fa477dd/d7ac816；不重跑旧review。

Task2 Ruling：原update_gate未识别新浏览器生命周期，主4方法RED后增加short_title_browser_gate.py与update_gate首入口钩子，4方法GREEN；纳入本次集成审查。源完整不等于浏览器已确认关闭；原锁和闭合原件都需检查。原smoke fixture把安装后已有state当不存在，exist_ok修正并保留失败日志；业务断言未修改。

独立6 Important主复现RED后修复：未打开close擦除launch隔离、旧/别frame请求贴新epoch及旧任务响应、重复JSON丢异店、深层异常丢异店、未核验vendorId替代literal venderId、probe与open/版本切换竞态。新增7方法：core25+gate5=30，当前完整focused GREEN。request开始事件与main_frame/phase/time绑定、歧义JSON和解析异常fail closed；共享install.lock持有完整会话/切换，仅资源owner能写closed。并发busy纯摘要不作为写许可；实际install/rollback强互斥，版本操作已持锁时阻止重开而允许安全版本操作完成，反向已有浏览器持锁阻止版本操作。
