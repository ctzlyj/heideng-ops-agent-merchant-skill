# 短标题持久原生 worker（私有研发入口）

商家描述目标；下列命令由 Agent 执行，商家不手填 JSON、Cookie 或上传模板。商家版独立安装后按需使用公开 PyPI 浏览器依赖；商家仅在必要时操作独立浏览器认证并对本次精确根范围明确批准。本轮仅合成/安装测试，无真实商家链路或公开商业分发验收。

## 正常路径

1. 先按 native-short-title-planning.md 读取全部原在售商品和兄弟 SKU、原 health 事实并审核具体短标题稿。取得不可变 planId；不能用长标题、health 标志或模板代替实际短标题来源。
2. `short-title-worker-start --plan-id <planId> --foreground`：只读启动。Windows 后台进程隐藏控制台，仅商家认证浏览器可见。重复 start 查询同一 worker，不抢其锁、不新开 actor。不得从 PID 消失、超时或连接失败推断可重启。
3. `short-title-worker-status --worker-id <workerId>` 查看是否等待认证、精确 root 的 importId/fingerprint、候选数量与最后状态。等待时不反复导航；身份必须来自当前自有页面的新鲜同对象 POP 响应。抓取模板、身份和原库存仍独立再核验。
4. Agent 向商家说明该 root 全部具体目标、批次和原生写入范围。取得本次明确同意后：`short-title-worker-approve --worker-id <workerId> --import-id <importId> --fingerprint <fingerprint> --confirm`。启动不是批准，开发授权不是店铺写入批准。
5. `short-title-worker-execute` 使用同样三个精确标识，返回稳定 requestId；`short-title-worker-command-status --worker-id <workerId> --request-id <requestId>` 读取原请求接受、dispatch 和独立回执。丢回复先读原 ID，不换 ID/工具重投。原动作未知、非成功或上传 binding 丢失，不重传、重点击、不推进后批。
6. 依次 `short-title-worker-results`、`short-title-worker-effects`（同样三个标识）提交只读原 C2/C3 回读命令；每次新的只读观察用新 requestId。C2 逐行成功不等于实际标题、正式审核、全部 health 与门户已生效；当前 C3 部分来源已接入，完整正式审核/门户/health 与确认失败子计划仍未完成，不称整店完成，不自动修复重投。

## 停止、恢复与证据

- `short-title-worker-recover` 只查询原实例和原件，不重上传。`short-title-worker-stop --worker-id <workerId>` 停止本机所属资源，不取消平台任务，不删除原件或解除 C3 隔离。停止事件在预检/health 返回后、原上传与创建之间、native dispatch 边界再次核验，阻止下一动作；不能中断已经派发的远端调用并假称未执行。
- broker 冻结命令接收、原浏览器/控制器实际关闭并核验真实 guard 后才保存 closed 和独立 close receipt；未知清理保留 guard，原 run 未确认关闭时不重启。
- 只有原 run 已确认关闭，`short-title-worker-resume --worker-id <workerId>` 才能启动严格 readonly 新 run；复用原 source/profile/root/runtime，不抓新 source，不重建批准。approve/execute 均被拒绝。没有原 root 的 readonly 恢复只允许查询和停止，不能猜原上传或创建结果。
- 原 attempt/dispatch/ack/observation/anchor 的已观测前缀在活动期间持续保存独立 hash 证据；原件删除/改变不能倒退为 not-started。命令接收提交与 owning-thread 校验同步，不把尚未写完的命令文件当损坏；未知前缀/回执保留隔离。元数据整体最多 16MiB，超限拒绝，不截断。
- 安装 archive 与完整文件集合 hash 固定到 job；native 动作前再核验实际已管理安装，不只看 VERSION。代码、原范围或原件变更即停。未知/活动/孤立 worker 阻止新写入、安装更新与回滚，精确当前 actor 只可用实际同线程同路径的两把锁作为 witness。
- 状态及 command-status 是历史回执/最后观察，不替代本次 fresh effects 读取。closed 仅代表本机资源关闭，不能代表平台任务结束或标题生效。已导入未完整 C3 核验依然隔离。
- IPC 仅绑定 127.0.0.1，精确 Host/job/fingerprint/local headers；拒绝 Origin/Referer/cross-site、重头、重复 JSON 键与超限正文。不保存或返回签名 URL、原 HTTP 正文、设备信息、Cookie、Token 或 Key。
