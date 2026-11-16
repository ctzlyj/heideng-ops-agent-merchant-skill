# 短标题确认失败修复准备与新批准：私有研发验证（2026-11-16）

本阶段推进整体商家单仓库目标，但不是完整失败修复或全流程上线。原生子导入上传/创建、其执行恢复、正式审核/门户与完整C3 terminal仍必须完成；不能把本轮准备/批准功能当作上述能力的替代。

## 实现与商家Agent入口

新增 short_title_repair 模块：不可变父任务关联、业务内容intent去重、完整原C2/C3来源证明、新精确批准及独立批准hash回执；全部原兄弟SKU保留。原worker增加repair-plan/repair-approve，CLI增加历史repair-status/rows，四类repair原件纳入native-prefix及关闭/更新/同店完整性校验。

实际prepare/approve在原owner线程和真实install guard内读取当前原实例全部C2逐行结果，核对整店及全部原兄弟目录、当前实际标题和完整v2健康列表/逐SKU详情。只接受原目标已确认failed且当前标题问题仍存在；新文案须经过审核，不覆盖已无需要的行，不与当前值或全部未改兄弟实际标题NFKC/casefold重复。历史status/rows不声称本次需求已核验。

原批准不继承。新repair fingerprint、confirmed和30~3600秒TTL精确记录本次意图；批准hash回执保护时间与全部内容，关联worker原前缀也须有效。新批准仍不是native child执行许可已接入：childImportExecutionAvailable/retryAuthorized/imported均false。readonly resume可读取/prepare但不能新approve/execute；stop和错owner/身份/范围保持拒绝。

## 实际验证

最终选定 **112方法通过**，0失败/0错误/0跳过，1225.953秒，231份源码/测试/参考文件hash未变。当前发现783方法，本阶段**没有运行当前全量**；旧745仅适用于dc4590a29e8f2d110849080bf2c913bfb5efc5d9，不能当作当前版本证明。

新HOME安装3方法通过：模块来自已安装包、默认managed-install verifier、实际owned localhost IPC、合成browser/client、原1次上传/1次创建、当前失败需要回读与新精确批准、完整5个原兄弟保留、同业务子intent去重、原前缀删除拒绝。native child尝试仍为0，真实商家调用/付费模型均为0。

最终archive SHA256 `7e057e5ef361d64c552d206dd3ec68433c53906d80659858632474c4ac2af7c5`，117源文件、118文件含package-manifest。归档源码与当前源码规范化换行字节完全匹配；包审计通过，个人路径/凭据模式/未知文件均0。这是代码/包审计，不替代第三方许可与商业分发授权。

## 实际失败与审查

新核心先真实RED（7新方法的16个失败子case；初始runner也误计入15个已导入旧health方法，共22，不能说22新测试）。修正test模块import别名和product/guard fixture后继续；首个绿色尝试有1个test harness AttributeError，因FileLock没有release方法，改为真实__exit__并移除已释放guard，未弱化业务guard。后续两个安全RED证明旧failure prefix与孤立空family可被借用，添加最新C2前缀和原父根校验后通过。

HTTP真实loopback首次1失败（42.888秒）：旧六字段parser拒绝新payload，命令未被受理，送达仍unknown；共享command_keys修正生产state/HTTP后原测试通过。精确parser测试插入最初产生转义SyntaxError、随后出现预期SafetyError，均保留，不当成功；纠正测试后实际断言RED再GREEN。Agent CLI原样提交文件读取函数的(value,hash)tuple，实际RED后仅取value；目录/参考说明也先RED后补齐。

独立审查发现3项Important，均用原合成来源实际复现RED（3失败，14.068秒）：批准前未刷新当前C2、TTL可被单文件改写、rows忽略孤立批准。补原结果真实回读、独立批准回执与worker完整性、统一family校验后4个精确回归通过（19.855秒）。独立有界复查16次预期安全拒绝，包含同时改批准和receipt但workerprefix不符、缺失/孤立回执、恢复原件后5兄弟恢复；没有该范围的新Important/Critical。初次review hash-harness遇Windows锁文件，仅排除锁文件后完成非锁文件无写入核对，不是放宽业务锁。Reviewer已关闭。此复查不等于全量或真实平台验收。

## 仓库、隔离与必须继续的工作

私有仓库ctzlyj/heideng-ops-agent-merchant-skill、codex/merchant-foundation，起点6ac603e85769a7cc6eff0543afe159584116b724。只推送私有研发代码，不创建公共release。内部版git status为空、1.5.4 /13692b759bd52e35c3670cf8fad5330e1bf2b576未动；视频上游本阶段未刷新，已审计基线0.3.0 /29548089f7b71ac77ddb584caac0966a98df24ab，不称最新。

本地repair元数据读取预算16MiB、每类原件目录最多10000文件、文案输入8MiB，超限拒绝而非截断；这是本地预算，不是平台规模保证。完整更大类目/规模、真实模板/UI与商家授权链仍未验收。

下一步按同一计划Task4实现精确新批准与原parent/child双证据的native子根、原owner例外而非任意排除、一次上传/创建与未知恢复、完整父子行结果。然后统一当前全量及新固定GitHub安装验收。正式审核/门户契约、安全未尝试及跨版本重建、远端视频采纳、真实商家/类目/规模、生成来源和分发/商业许可仍未完成。不调用真实OAuth/jdo/info/商家API或店铺写入，不花钱生成，不发送消息或公开发布。整体goal与C3保持active/incomplete。
