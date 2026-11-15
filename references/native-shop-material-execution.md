# 整店可用素材的统一范围批准与执行

商家说“维护这家店全部在售商品的素材”，Agent先执行native-shop-material-audit.md完整库存/素材核对，再整理已有合规素材和真实卖点；不能以低分行代替全部SKU，也不让商家逐商品写命令/JSON。新增生成来源仍等待选择，不自动使用员工模型。

## 准备与完整余缺

1. 取得原auditId/fingerprint，要求库存、兄弟SKU和素材来源完整稳定。健康分未请求/缺失/无效独立报告，不造0、不按分数缩小范围。
2. Agent从原商品和用户合规素材中整理 ready changes 文件：每项含 productId、skuId、slot、review=passed，加原已核验 uploadTaskId 或真实 text。图片沿用native-materials.md的独立上传批准/回执/图片ID证明。不得凭URL冒充已上传图，不把测试中的review当真实商品验收。
3. shop-material-plan --audit-id <原ID> [--changes <Agent生成的文件>] [--target-slots <明确槽位逗号列表>]。默认全部支持槽位 white/scene1/scene2/selling/transparent/point1/point2/point3，缺模型不能静默只做文字。只有用户明确限定目标时才传target-slots。没有ready变化也保留全店余缺报告，不创建业务任务或虚构已处理数量。
4. 本阶段只补真正缺失槽位，不覆盖旧非空/空/驳回/待审素材。报告 awaitingMaterialCount、existingEmptySlotCount、existingRejectedSlotCount、existingPendingSlotCount、existingUnknownAuditSlotCount；驳回/空槽修复与短标题是后续步骤。部分可用范围的成功不等于全部店铺维护成功。

## 一次批准、逐块执行

根planId/fingerprint包括原审计、目标槽位、所有准备好变化、能力快照、实际运行版本及逐商品分块引用；默认每块<=50SKU，不跨商品混成请求。商家只确认Agent展示的店铺/范围/数量/保留与余缺，不手填指纹。

shop-material-approve --plan-id <ID> --fingerprint <原指纹> --confirm [--ttl-seconds 900]，仅当前明确范围。独立根批准原件保存，同一deadline传给每个子任务及官方签名/最终HTTP边界。不能靠task-approve给子任务延期或绕过根批准。

shop-material-execute --plan-id <ID>：开始时复核完整在售目录，每块复核其父商品当前仍在售（已支持productIdList过滤）、完整兄弟SKU/状态、原缺失槽、当前原生卡和上传来源，再通过Operations和官方京麦CLI执行。每块保存原attempt/ack/anchor及对应根批准，原字段读回后才推进下一块。实际子派发只能通过根runner在完整目录复核后建立的运行时能力；task-execute不能作为绕过整店检查的另一入口，也不接受持久化布尔标志来伪造已复核。

unknown、已开始未决、原件缺失/矛盾、非法owner、同店原证明伪装另店、链接或未知格式证据时拒绝重提；不推进剩余块，不换Profile、意图或transport。根/子/原审计/index的精确双向关联也纳入安装更新门禁，恢复清理不先删证据。保留根而子证明丢失、或attempt仍在而journal身份/指纹/根证明被改写，都须停止其他同店新写入。根文件本身丢失但批准/index/原子journal仍留时也不得换根；一律复核这些反向链接。只有本次合法准备调用刚创建的零attempt子ID可在根尚未落盘时短暂存在，历史孤立证明不能获得例外。

已知完成部分可读回后继续未开始尾部；如确需续批，同一根范围仅在无unknown且有未开始块时，经用户明确确认后更新当前批准，原历史批准和已执行尝试不改。仍有效的同范围批准无需反复询问；不得自动延长过期批准。如果原根批准明确仍有效、仅尚未开始子任务的本地批准写入被中断，Agent可用原指纹和根deadline恢复相同范围子批准，再由根入口继续；不能重新批准或重提有attempt的未知任务。

## 如实报告与恢复

- shop-material-status --plan-id <ID> [--refresh]：摘要不输出全量ID；refresh仅对原任务做原生素材读回，不能把未知提交的目标匹配变成原调用成功。
- shop-material-rows --plan-id <ID> [--view coverage|chunks] [--page 1 --page-size 50]：所有在售SKU及目标槽位覆盖和原任务分块均可分页读，不拿一页说全店。
- allReadyChangesVerified 只证明本次准备好变化的原ack与支持素材字段读回；auditApprovedForWrittenChanges、全目标槽位内容、健康分/门户信息分分开。scoreRecalculated始终false，不声称平台分值已刷新。
- 执行结束再次查询整个在售目录及每个捕获商品全部兄弟SKU状态；新增SKU/商品或状态变化则 currentCatalogScopeVerified=false，原已知写入仍按原范围报告，不改成unknown或扩大重写。此观察仍非事务快照。
- 默认status是历史范围，currentCatalogScopeVerified=false；catalogHistoricallyMatched和catalogObservedAt只说明最后观察。只有本次execute实际完整复核通过才在返回中标当前目录范围已匹配。

本版本仅合成/安装/官方源码边界验证等级，不含真实OAuth、当前认证卡、API写入、平台审核、商品视觉品质或信息分等价验收；真实商家范围另需明确批准。生成服务来源、对外分发和商业权利仍未确认。
