# 原生已有视频上传和保存

商家只描述目标，Agent执行以下流程；不生成视频、不读取任何公司模型Key，不替商家使用集团额度。

## Agent流程

1. 先确认已连接的是商家本人POP Profile；不可default/员工Profile。已有视频先按local-video-handoff.md完成真实技术检查及实际视觉/试听确认。
2. 获取当前店铺视频素材空间zoneType2，读取当前prod元数据卡，确认原生地址分配、保存、精确视频查询的输入合同可用。不可切pre或改接口猜参数。
3. `video-delivery-plan --profile … --manifest … --zone-id …`只做读取和准备，不申请签名地址、不上传。Agent展示店铺、原视频/封面/商品上下文、名称和执行范围，取得商家对实际上传/保存的明确批准。
4. `video-delivery-approve --session-id … --fingerprint … --confirm`保存独立父批准和deadline。首次执行前可由用户重新批准；任何已启动阶段都不能借改journal或子任务延长原批准。
5. `video-delivery-execute --session-id …`：最多一次新jdVideoId分配、一次完整multipart传输和一次保存。传输字段是video_file，不是PUT；使用原视频原字节，默认不转码/修复。仅当已确认没有启动HTTP传输时，允许一次以原jdVideoId+breakPointFlag重新取地址，不新建ID、不换素材。
6. `video-delivery-status --session-id … --refresh`精确查询原videoId/jdVideoId。无refresh仅历史状态，storageVerified=false；新查询无原记录降为saved，不能继续当ready。报告转码、审核和原字段核对分别完成与否。

**当前边界：只接上传/保存及元数据核对；SKU绑定还未接入。** 不允许通过generic task调用地址分配、视频写接口或绕过现有素材42证明guard。整店/单SKU绑定需下一阶段独立范围、实际标签、父批准、<=50SKU分块及关系审核回查。

## 安全和恢复

- 地址分配虽为GET，按有副作用动作处理：冻结实际店铺认证上下文，批准后才调，最终签名/HTTP边界检查deadline，禁止SDK业务请求重试和SSL辅助的第二次业务HTTP尝试。保存同样使用已审核官方stdin路径。
- 签名URL仅由官方分配响应进入单次grant对象；不接受用户URL，不JSON/pickle序列化，repr隐藏。worker stdout仅用于父进程受控捕获IPC，不作为CLI输出/日志。禁止原认证Key/Token被回显为grant。
- 仅官方返回的公开HTTPS目标；无代理、无重定向，DNS固定公开单播地址，保留原host的TLS/SNI验证。不给上传端JD Cookie/Authorization；不记录URL、IP、响应原文或原始错误。
- 先有界制作相同hash的私有原字节快照，避免连接期间原文件变化造成上传未批准内容；最大500MiB。HTTP200也拒绝可识别的负业务响应。完整发送+2xx仅证明收到传输响应，不能单独证明存储/审核/绑定。
- allocate/renew/transfer/save调用前写不可覆盖尝试记录；原始非敏感回执、独立anchor和父批准交叉核对。journal丢失但有尝试/回执/anchor/批准证据时不能丢掉隔离，每条遗留记录都须有完整合法且彼此一致的owner，不能忽略无owner记录或将空owner当另店；来源不明则安全阻止写入，仅完整证明另店的证据不牵连本店。已有receipt/anchor但attempt或journal链接缺失时拒绝重放，阶段开始前再次检查独立原始证据。
- unknown只读观察原ID，不因目标值一致而清除，不重新提交。known transferred可以继续尚未尝试的save；正在分配/传输/保存时中断或缺少原始证明则保留unknown。恢复仍使用原批准deadline和原视频hash。
- 新分配不得复用本地其他同店会话的已知ID再覆盖其素材；已存素材的明确复用属于后续绑定步骤，不用再上传来替代。
- 视频元数据scopeSet=[BASE]、videoType=1，排除员工/创作者类型。videoId是商家素材主键，jdVideoId是平台原ID，两者不互换。status2仅转码成功，4才审核通过；3仍审核中且不自动等同转码已证明。
- 只保留精确IDs、名称、原声明size、时长和状态等必要字段，不落盘播放签名URL。元数据核对不证明远端原始视频hash/像素或自动封面与本地封面一致（remoteOriginalBytesVerified=false）。状态2/4的时长需符合原完整解码时间线的整秒范围。

## 开发验证级别

本版本仅私有研发，真实商家授权/上传/平台审核均未实测。离线使用合成API/连接；安装smoke实际安装公开解码依赖、解码合成MP4、运行生产multipart代码，但不进行真实网络上传。另一项测试使用SHA核验的官方0.3.7源码实际parser/signing、最终HTTP模拟及socket拦截，不替代真实OAuth或native输出卡验收。

没有经审核的当前卡/版本/权限或没有写入批准时应安全阻塞，不让商家自行写命令/JSON补洞。接口由Agent执行。生图/生成视频和正式分发/商业权利仍待用户确认。
