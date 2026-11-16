# POP 成熟源码迁移（2026-11-16）

来源 `ctzlyj/jd-material-pop-skill`，嵌套 `jd-material-pop` 2026.11.207 / `b56b22376db88182352d3f64ea3e9752d4ae5677`。
用户确认必要代码/模板在私有商家仓库和安装包分发，未附许可证不改写成 MIT。

## 实际恢复
`jd_material_agent.py` 的审计、计划、素材规范化/上传绑定/回执核对、模板导出、冻结 SKU 短标题校验交付；
`pop_workflow.complete_short_title_import -> pop_browser.import_short_titles` 自动分批、平台 createImportJob 接受、结果处理和未知不重发；
`pop_cutout.py` 的固定 SHA 本地抠图；两份正式导入模板；原 large-body bridge/interface probe。
这些是必要原始源码/依赖闭包，不是新商家授权、标题或素材状态机。

## 薄适配/退出
原五/六公司生图池收敛为商家 LTS4AI gpt-image-2.5，实际协议由 `MerchantImageClient -> lts4ai_client.SfImage2Client`（sufy）承担。
未知付费请求不循环切模型重提；公司 JoyAgent fallback 明确拒绝。原未选定的文本/视觉模型入口在 HTTP 之前拒绝；不声称模型自动写标题已配好。
保留原 Agent-authored 冻结 SKU 表/标题校验和自动导入，不让商家手工重复上传。原个人 startup/login/bootstrap 未复制；安装和连接使用独立安装层与成熟连接器。
模型权重不分发；保留来源许可元数据和 SHA 白名单。当前没有下载权重或运行神经推理。

## 验证和剩余衔接
本地跑实际模板校验、真实源码导入、单次 LTS4AI adapter failure 不重提、未配置文本/视觉不启动 HTTP；原业务历史验收不替代本次真实商家适配。
未执行真实上传/绑定/短标题 createImportJob/审核回读/付费生成。
默认连接器 HostBrowser 不能仅凭 contextId 变成 POP profile-dir；真实 owner/Profile 交接仍待实现和验证。全量整店刷新、诊断/视频来源仍待迁入，不能宣称整目标完成。


### Owned browser handoff adaptation
已增加最小衔接：HostBrowser 在原 owned/同 context 回报通过后，可接收实际任务控制器提供的 `profileDir`，只接受 merchant 状态目录 `browser-profiles/` 下的现有目录，不读取/复制 Cookie。
原 BrowserAuthJob 完成实时 CLI 身份核验后，沿用 `shops.json` 的 extra metadata 保存目录；POP 原 `complete_short_title_import` 在未提供 profile-dir 时，仅在 Profile 与本次已核验 seller 身份相符时自动使用该目录。
没有目录、目录非本任务 namespace 或店铺不符则沿用原 blocked-browser-profile，既不猜工作浏览器目录也不触发另一次授权。
这是跨模块适配，不是新的授权/标题状态机。已跑真实原函数+受控导入回执 fixture 验证自动衔接；fixture 返回 verified 不代表真实平台导入已验证。
实际宿主持久目录、登录态、OAuth/导入均尚未执行，因此原文“待实现”是此补丁前记录；当前剩余是宿主接入/实机验证。
