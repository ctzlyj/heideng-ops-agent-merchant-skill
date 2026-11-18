# 商家体验薄适配 0.4.4

## 实施
- 默认status保留兼容字段，给一屏商家摘要；--detail查看完整来源/能力。原技术回执仍保留。
- 素材merchant result增加完成/审核中/需处理/未知核对、可离开与下一动作；pending不是失败或完成，unknown不重试。
- 同店pending-auth普通重试自动resume，mismatch/凭据隔离不盲目恢复；--fresh明确新会话。浏览器会话按店铺隔离目录。
- mature run自动begin/heartbeat/end版本usage，原安装锁/快照/未知回执保留；更新worker detach与连接器一致。
- 导航新增商家短指南，技术细节仍在模块页；生图提示词原文未改。

## 验证与边界
本轮只做状态/恢复/租约/打包和成熟路径离线测试；不真实扫码、店铺写入、付费或定时经营。真实WorkBuddy登录/OAuth、长任务跨宿主刷新与多店浏览器需要内测。已保留原始merchant-result/task/receipt供实际恢复。
