# 持续短标题 worker / 商家 CLI 实施计划（2026-11-16）

> executing-plans + TDD；当前源仓库独立于内部版，业务测试仅 synthetic。没有真实 OAuth/jdo/browser/API/写入/模型/消息/公开发布授权。

基线 a1ff9869ef9090cc0778623f4cbc62ced9dd4059；C3 partial 已有代码，但完整正式审核/health/门户、失败子计划和最终 terminal 门禁未完成。目标仍是商家安装一个仓库后由 Agent 自主完成流程，不以 API/导出替代最终入口。

## 文件与任务

1. `short_title_browser.py`/`short_title_import_browser.py`：真实 borrowed install.guard 支持；同线程/同路径、未知关闭保留、旧调用行为不变。tests/test_short_title_worker_guard.py 已真实 RED 5/6 failures，再 GREEN 5/1.170s。
2. `short_title_worker_state.py`：不可变 job scope（原 plan/shop/source ID/已校验安装 archive+files hash）、原 root link、一次 run launch、command acceptance→dispatch→receipt；元数据只安全字段/非私密 IDs。不存在 dispatch 不是未知动作可重投证明。
3. `short_title_worker_broker.py`：只绑定127.0.0.1；精确 host/job/fingerprint/local headers，拒绝 origin/referer/cors/query/重头/不完整/超限/私密 body。HTTP线程只排队，原 owning thread 执行 native动作；相同request ID不再次执行，换内容拒绝。回报摘要及历史 command receipt，不回传原JSON/URL/keys/完整大表。
4. `short_title_worker.py` + `scripts/short_title_worker.py`：同一个 outer install.lock 和 home-owner lock贯穿 source→root→批准等待→一次 execute→原 C2/C3；B1/B2转换不释放guard。start只是readonly。代码manifest和root/source前缀每次动作核对；闭合原资源/停broker后才写原run closed receipt。未知不重启、不把心跳/PID缺失当没执行。
5. `short_title_worker_service.py` + CLI：按需公开BrowserRuntime；Windows后台无console，foreground只用于必要的商家浏览器认证；启动argv只有state/job/run等非私密标识，safe environment。start/approve/execute/observe/effects/recover/status/command-status/stop 交给同worker，不二次抢install.lock。状态/历史分页不代替当前源回读。execute ID默认稳定，丢回复先读同ID；approve需本次root明确确认。
6. 严格原run confirmed-closed readonly resume，绝不基于观察超时启动新actor；原 source/profile/root/runtime复用，已upload失去binding禁止重传，unknown create只recover。代码/原件变化阻断，新源或新job不能绕过旧unknown。
7. 所有 worker unknown/active/孤立 launch/command 原件加入 installer/write gate；closed local worker不代表server job/C3完成。正常无attempt/root C3无记录的已确认readonly stop才可idle。
8. installed fake-browser+真实loopback smoke、bounded独立review、完整当前发现集合全套与包脱敏、actual pinned私有GitHub新HOME验收。不要每个函数跑旧5000+1大回归；统一在worker阶段收口。

## 契约与测试门禁

- runtime_binding来自当前managed install verify_install，不只信VERSION=0.1.0；任务记录archiveSha256和文件集合hash。Unit可明确inject synthetic binding/factory，生产CLI无此选项。
- body最多4KiB、命令/数量有限；关键值仅job/root/request IDs和精确指纹、确认bool与有限TTL。Signed URL/凭据不得进argv/JSON/日志。
- request验收与native dispatch独立，write一次dispatch先落盘；队列reply丢失、worker退出中断、receipt缺失、旧/错run、错店/root、版本/安装文件改变、伪造/孤立记录都拒绝重复派发。
- HTTP native动作由owner线程且复用actual guard；健康分审计approve使用live_browser witness。Stop不取消商家server任务，不删除任何原件。
- Root/mode变更与scope过期不能用旧批准。失败子计划仍需完整C2确认失败、当前实际需修复和新root批准，success/unknown/awaiting audit不重投。

Ruling: 使用现有auth_broker的loopback隔离模式及稳定非私密command ID，不引入新账号/代付/SaaS — 原生业务批准仍由root manager验明，不从start推导 — 成本是必须证明origin/host/header/queue边界及相同ID不重派。
Ruling: 当前正式短标题审核与门户契约未确认，worker可持续承接已有真实读取API但完整terminal保持未证实；随后继续补原来源/失败子计划 — 不伪造接口也不把partial当最终状态 — 成本是当前C3不能释放业务/update门禁。
