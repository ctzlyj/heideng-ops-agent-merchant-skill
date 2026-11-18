# 0.4.6 根因审计后的契约优化：0.4.7 代码候选

日期：2026-11-18（Asia/Shanghai）。基线：1d93a4e / 0.4.6。原报告与复现数据只读。

## 审计要求逐项映射

| 要求 | 本轮改动 | 可核对证据 |
|---|---|---|
| F01 真实状态/分项结果 | 只读投影识别空任务、准备、已提交、待审核、失败、未知；汇总素材/短标题/属性/修复/外部素材；保留修复行与失败数。命令返回不当作仍运行，默认不建议重提。 | tests/test_audit_contracts.py 中报告返回结构、实际repair结构、分项阻断完成、标题失败数、审核/已过审区分测试 |
| F02 默认status | 默认不扫描/展开capabilities与commit清单；仅摘要，--detail保留技术来源。 | 默认CLI输出体积/内容测试，旧status --detail与坏更新配置兼容测试 |
| F05 错误接线 | 主CLI与现有mature_entry异常边界调用中文投影，技术原因脱敏；Agent诊断和本人决策分开，不再因技术失败设needsUserAction。 | 真实成熟子进程读取不存在模板的结构化错误测试；主CLI脱敏/责任区分测试 |
| F03 生命周期 | 登录与OAuth共用单调时钟预算，阶段变化输出脱敏事件；超时/中断由原worker核对原Profile、收尾本任务回调/浏览器、join后关闭HTTP服务，退出不谎称后台运行；资源关闭失败不宣称完成。 | tests/test_audit_connection_contracts.py 中共享预算、晚登录、时钟调整、阶段事件、worker关闭失败、中断、终态及原Profile核对测试 |
| F04 ID-only | 可靠页面店名仅作为已登录会话证据，原期望venderId保持；最终官方核店仍严格匹配完整ID，错店仍mismatch。 | ID-only入OAuth与错ID拒绝测试；原官方身份测试 |
| 最小跨模块交接 | 原plan返回hostHandoff文件，列精确商品事实/待补ID/schema/文本属性命令/原目录恢复命令；工具不替宿主做经营规划或授权决策。 | tests/test_audit_handoff_contracts.py 中交接消费者格式与精确命令测试 |
| 同任务全文件→子集 | 只有任务内文件通过原店铺、原目录、源表SHA、冻结计划校验后投影；目录外全店文件及计划外ID拒绝。单SPU保留完整批次签名/兄弟回执。 | 真实冻结计划/Excel状态回归，外部输入与跨店拒绝测试 |

## 明确不做的事

- 没有新增调度引擎、授权系统、任意执行口或第二套审批。
- 没有修改 `_shared_image_rules` / `image_prompt`；没有恢复公司模型、员工SSO或个人Key。
- 没有真实扫码、登录、京麦写入、付费生图或向商家发消息。
- 原报告中“真实宿主窗口、登录→OAuth→ready、超时离开恢复”的实机验收须另获授权后执行，不由离线回归替代。

## 验证与发布门槛

本轮定点测试使用实际函数、原冻结计划和原成熟子进程；外部浏览器/官方OAuth只用合成替身，不能作为实机已连接证据。完整离线套件、原更新器、源码固定包一致性及最终提交将在完成后登记。

## 兼容变化

- 默认status不含顶层capabilities，需要技术清单改用--detail。
- 连接进度为逐行JSON事件，最后一条为最终结果；宿主不要用head截断活命令，也不要只读取首条事件当成最终ready。
- `needsUserAction` 不再指向所有技术失败；`needsAgentAction`负责可诊断/回执核对，`needsMerchantAction`只用于明确本人/决策请求。
- 软件发布通道的签名与固定包证明代码可安装、可复现，不证明真实店铺端到端体验。

原审计报告SHA256：45f57b4f68ffaf71aa0ef9a551fe81aeea160f14d5ff1e70fc20f33efbbd9386

## 发布候选的最终离线证据

- 定点回归：28项（后续补充原plan入口产出并由原解析器消费argv的集成验证，共29项）。
- 最终可用性套件：185项；含原更新器从0.4.0升级当前候选、私有状态保护、原生图提示词原文一致性。
- 固定包：`updates/artifacts/heideng-ops-agent-merchant-0.4.7-ef7955e5ebb4.zip`。
- SHA256：`ef7955e5ebb477f35afe3292b3c76dc8379082a280b47bded2d5b1607bd8aef5`；签名索引序号8。
- `tests/test_release_consistency.py` 已验证源码重建与固定ZIP逐文件及总SHA一致。
- 旧目录23项保护哈希保持一致，mature provenance保留原上游commit，提示词原文未变；没有真实店铺写入或付费任务。
- 发布通道仍沿用既有签名固定包机制，发布注记明确“Code/offline verified; real host/shop acceptance pending”。它不是WorkBuddy/Windows可见页面或真实商家授权通过证明。
