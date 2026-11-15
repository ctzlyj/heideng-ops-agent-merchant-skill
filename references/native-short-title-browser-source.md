# 短标题B1浏览器原件（内部适配层）

B1提供task-owned持久浏览器读取与独立source原件；没有上传/创建实例/写入批准，也尚未接入商家CLI/后台worker。这不是完整自动导入上线，A1/A2入口仍明确planning-only，B2/C必须继续实现。

- ShortTitleSourceBrowser仅接受原ShortTitlePlans及原完整审计的明确shop/profile。state内生成会话独立context-data；不接受任意profile目录，不连接工作浏览器/员工Cookie。公开Playwright依赖由现有BrowserRuntime承载；生产接口未运行实店。
- open/poll保留商家必要扫码界面；capture导航商品页，在当次同一页面网络JSON对象内核对shopName/venderId/shopId和显式POP，不拼对象，不用登录前旧proof。来源不完整/出现异店即停止。数字店铺类型没有核验契约，不能猜。
- 只读打开原短标题抽屉，要求queryByPage的确切可信origin/method响应与成功code；当前支持已验证合成schema的一页batchJobRecordDtoList，明确taskListComplete=false。jobId是类型而非实例；只报告实例字段且不以页面缺少ID证明未提交。
- 从当次drawer里选择唯一可见模板下载link；origin有界、响应URL必须和该link原href精确一致，文件名由Agent生成，不使用远端suggested_filename。下载不明确/链接不支持/模板危险或超体积时停，不取内部缓存或猜REST。
- 原模板与独立observations、source、owner共同绑定原planFingerprint/审计/同店/来源hash。前后库存和全部兄弟关系复查；原scope/模板/owner或主source重新hash篡改不能替换独立observations。status/read_source只是历史捕获，不称当前身份/平台规则/导入成功，approvalReady=false。
- 原JSON、DOM、Cookie、签名URL不存进记录或回复；仅必要公开shop/实例字段与hash。浏览器本身的私有profile留商家state，不进安装包/Git。关闭/launch结果不明确的profile隔离，不重新打开；无法确认只保留具体阻塞。

实际schema、数字POP类型、分页、模板入口/redirect和平台更新仍须在另获授权的真实merchant现场确认。B2继续同会话精确批准、文件hash/原行/分块、upload/create-instance独立回执、unknown只读恢复；C继续逐行结果/已确认失败行修复与原标题/审核/health回读。不得用B1原件绕过这些门禁。

更新/回滚门禁已纳入B1：活动/关闭或launch未知会话、缺失owner/原件/模板、错误源/孤立证据都阻止安装与恢复；仅已确认关闭且锁可取得、原件全部完整的只读会话可空闲更新。门禁不扫描浏览器Cookie内容。

审查修正：identity必须literal venderId，vendorId只可核对别名；拒绝重复JSON key和非有限JSON，解析/遍历失败把当前来源置未知，不丢已见异店。request事件在当前capture/document/main frame与当前drawer phase内开始才可读其response，不能把晚到旧响应贴新epoch。只有持有原资源/锁的实例可确认closed。浏览器持有与安装/rollback相同install.lock整个会话，版本切换持锁整个恢复/切换；busy摘要本身不是并发写入许可。
