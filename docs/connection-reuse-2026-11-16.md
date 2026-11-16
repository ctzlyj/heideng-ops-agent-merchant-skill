# 成熟连接器迁移（2026-11-16）

- 来源 `ctzlyj/jingmai-cli-linker` 1.0.2 / `1c438fc5419cd86f709cc4a501325782fd4a1e36`，从 Git blob 选择必要源码/静态控制页/桥接说明。未复制个人配置、凭据或历史。
- 用户确认了上一条请求的私有商家仓库/安装包分发范围；`DISTRIBUTION-PERMISSION.md` 记录范围，不冒充 MIT。
- 原实际执行链 `scripts/linker.py -> app/shoplib.py.resolve/verify_profile -> app/server.py -> browser_auth/browser_adapters` 保留。
- 新增 Profile 自动命名增加商家目录 hash 前缀；已有同 namespace 授权按原方式复用，未强迫增加新证明。系统凭据槽是否彻底隔离仍待真实授权验收。
- 商家 `JDO_HOME`/`JDO_CLI_HOME`、linker 状态/端口独立。去除员工开白表指导；官方 CLI 安装复用本包原有公开下载/校验薄适配，OAuth/身份仍走原成熟代码。
- 后台服务通过同一隔离 `mature_entry.py` 启动；升级只调用已校验安装源自身的 idle-only `/api/shutdown`，不新增授权审批层。Windows port_owner 原逻辑保留；POSIX 用 lsof/ps 元数据，不向回调端口发空连接。
- 本地适配测试包含原 ready 分支不启动授权、实际原服务启动和空闲关闭、包内入口可达、目录与 Windows/POSIX元数据适配。不是实际店铺 OAuth 或系统凭据验收。
- 未执行真实登录/扫码/OAuth/verify 已授权 Profile。macOS native credential transport 保持明确未验证，不宣称宿主全支持。
- 默认 HostBrowser 的 owned context 与 POP 短标题持久 profile-dir 对接尚未完成；应沿用原浏览器身份来源和任务 owner，不编造身份脚本或导出 Cookie。


### Owned browser handoff adaptation
已增加最小衔接：HostBrowser 在原 owned/同 context 回报通过后，可接收实际任务控制器提供的 `profileDir`，只接受 merchant 状态目录 `browser-profiles/` 下的现有目录，不读取/复制 Cookie。
原 BrowserAuthJob 完成实时 CLI 身份核验后，沿用 `shops.json` 的 extra metadata 保存目录；POP 原 `complete_short_title_import` 在未提供 profile-dir 时，仅在 Profile 与本次已核验 seller 身份相符时自动使用该目录。
没有目录、目录非本任务 namespace 或店铺不符则沿用原 blocked-browser-profile，既不猜工作浏览器目录也不触发另一次授权。
这是跨模块适配，不是新的授权/标题状态机。已跑真实原函数+受控导入回执 fixture 验证自动衔接；fixture 返回 verified 不代表真实平台导入已验证。
实际宿主持久目录、登录态、OAuth/导入均尚未执行，因此原文“待实现”是此补丁前记录；当前剩余是宿主接入/实机验证。
