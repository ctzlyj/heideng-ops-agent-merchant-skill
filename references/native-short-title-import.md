# 短标题原生执行 API（持久 worker 已接入，完整 C3 待完成）

本API会真实触发原商家抽屉file.upload和createImportJob；部署仅私有研发，未执行真实商家链路，不是最终商家自动导入上线。商家不手工上传；Agent可在同进程原生浏览器内执行。CLI 持久 worker/execute 入口见 native-short-title-worker.md；C1/C2 原实例完整逐行处理结果已接入只读 API，C3实际短标题/审核/health/门户回读与确认失败专属修复仍必须随后实现。

## 原件与动作

1. A1/A2原完整库存/health问题与已审核稿，加B1真实当次商家browser source；完整source/模板/ScopeFp、全部5000行批次与文件/行hash组成不可改root。相同intent不能换source替代旧unknown任务。
2. CLI short-title-import-plan/approve/status/rows供Agent使用；approve需用户对本次完整root fingerprint明确确认。proposedRowCount不是实际更新量；开发授权不能作为此业务批准。
3. 仅ShortTitleImports.execute(importId,ownedBrowser)是原生执行API。浏览器继承原商家source/profile，fresh request/main_frame/phase身份与模板核对；每块提交前新完整原生health来源核对目标仍为已知标题问题。材料缺失/分数缺失不据此漏SKU。
4. 独立attempt先于动作；transport在读取原批准/attempt后先登记一次dispatch，再原抽屉唯一file input/确认button。upload业务接受、create业务接受、actual实例和原object/time/current task anchor均分开；jobId不能当实例。任何未知/非成功都停，不换工具重传/重点击、不推进后块。
5. recover只查询原同店task页：必须原上传object、原创建窗口和唯一actual实例（不是从文件名或类型ID猜）；重复候选即unknown。task页只是当前一页，不以未观察到证明任务不存在。若独立observation已写而anchor失联，沿原observation核对，不新建任务。
6. 已确认upload却原DOM/live native binding丢失，不重新set_input_files；没有核验的恢复binding契约不能猜组件状态/REST，只报告具体待恢复。已create attempt无论断线/回复丢失都只能原件查询。

## 边界

- submitted-awaiting-verification只证明匹配实例，不是标题生效。imported/actualTitlesVerified/healthVerified仍false。C1/C2完整原实例处理结果可令rowResultsVerified为true，但不是实际title/audit/health验证或重试批准；详见native-short-title-results.md。非成功响应也不能证明绝对没有提交；可由原任务只读证明修正关联，不自动重试。
- 修改任一未来批次文件、原批准、attempt/dispatch/ack/observation/anchor或丢失已执行前缀不允许提前写。完成原件完整的无attempt prepared可idle；任何已尝试/unknown/submitted/孤立原件阻止安装/恢复/回滚。旧runtime根计划不自动写或混用批准。
- browser持有共享install.lock整个会话；内联新health审计只复用实际同线程/同路径仍持有的FileLock witness，不释放或绕过互斥。普通审计仍取得install锁再audit锁。
- 只存非私密公开字段与hash：不存原JSON/DOM/请求正文/签名URL/Cookie/设备信息。responseSha256是已完成的浏览器body；压缩后Content-Length不是解码body的线长证明。原图片HTTP字节证明逻辑不改变。
- 对真实平台type/schema/pagination/template/redirect、真实结果文件/原title来源、其他操作员并发修改的服务端CAS/类目/规模验收与分发许可尚未完成，不冒称已获商业化或全平台等价性。

这些限制不是export-only替代，完整 C3 与真实商家验收依然是商家版目标的必须部分。生图、生视频来源等用户确认，内部版与个人Skill只读。
