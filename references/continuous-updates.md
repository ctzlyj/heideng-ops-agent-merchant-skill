# 持续更新：维护候选与商家稳定升级分离

## 商家：安装一次，默认开启入口触发的空闲升级

0.4.0安装器默认建立更新配置与公钥pin，使用现有隔离运行环境准备更新验签依赖；不是业务授权。0.3.1及更旧安装尚没有更新组件，需要宿主首次升级到0.4.0，之后不必每次理解Git/终端。

默认24小时检查；正常任务结束/status入口轻量触发一个隐藏的短生命周期worker，不阻塞业务。没有使用入口时不会创建系统常驻任务；失败15分钟起指数退避、最多7天，原版本继续用。成功静默，不弹登录/扫码或更新确认，不重启宿主、不清空聊天、不经营巡店、不发消息或调用模型。

Agent内部入口：`python scripts/merchant.py update status|check|apply|enable|disable`。商家说“关闭自动更新/开启自动更新”，宿主执行对应命令；开关持久保留，正常重装不重置用户关闭选择。用户也可明确首次安装 `--no-auto-update`。检查失败的status记录原因，持续失败/需要本人私有仓库权限时才说明；不反复弹窗。

更新目标只来自已pin公钥验签的稳定索引；候选/withdrawn不安装。包使用固定Git blob位置、大小、SHA和manifest/兼容信息，不下载分支ZIP。每次切换重新取得签名索引，校验撤回与sequence防回退，不能拿同一位置ZIP+hash充当发布身份验证。

## 私有访问和首次信任

源是获准商家选择的私有商家仓库，包内公钥来自这一首次可信安装并持久pin。后续新包不能悄悄换pin。签名私钥仅维护者本机私有状态，商家只收公钥。

客户端Git缓存独立，不git pull安装目录。Git只委托**商家本人电脑**现有Git credential helper访问被授予的仓库；不导出/传递维护者Token，不自动登录，不读取JD业务Key。无Git或本人账号没有仓库读取权限时，更新保持deferred、原业务仍可用，需要宿主准备Git或负责人授予只读权限；私有链接不是所有商家天然可访问的公开发行源。将来公开发行是另外的权限/渠道决策，本轮不公开仓库。

## 当前任务版本、磁盘版本和宿主刷新

所有任务开始（含宿主直调官方工具、局部脚本和读取黑灯资料）由宿主执行：

```text
python scripts/merchant.py update usage begin --task-id <本任务唯一非敏感ID> --component <相关组件>
```

返回 loadedVersion/packageRoot：本任务从该程序快照读取经验/源码/执行工具，商家状态仍指向原独立目录，不复制记忆/Key/浏览器/运行数据。run原共享安装锁继续生效；快照只包含已校验安装清单。使用期间/每步前 `usage heartbeat --task-id ...`，任务结束 `usage end --task-id ...`，空闲时可完成已下载升级。租约默认2小时，过期不让无关历史任务永久阻塞；老快照和原任务回执仍保留，不因过期删除。

未知写入可用 heartbeat 的 `--receipt <原业务回执路径>` 记录恢复引用；它只是版本使用/恢复标记，不复制凭据或新增业务状态机。实际unknown由原业务读取/关联远端处理，不能因软件升级重提。旧快照不自动垃圾回收，避免破坏恢复。

磁盘更新后status显示diskVersion与hostRefreshRequired；当前任务/聊天不声称已经自动换掉加载的 Skill 代码/经验版本；这不限制任务生图提示词按需要重新设计。WorkBuddy/JoyCode在允许的刷新节点/新任务加载新版；如宿主缓存仍旧，由宿主安排重新加载或新任务，不能擅自重启/清空聊天。此协议未做所有宿主实机验证，宿主必须实际执行使用标记，不能声称捕获了所有隐式文件读取。

## 失败、撤回和恢复

本地文件被修改/安装是开发链接，拒绝静默覆盖。下载/签名/hash/兼容失败保留旧版。活跃使用或原业务安装锁/连接任务忙则延后。切换原install-journal与backup用于进程中断恢复：`update repair-switch`，复用原恢复机制。

常规升级仍拒绝降级和同版本异包。受控旧版恢复必须同时有签名索引的from/to精确SHA授权、仍稳定的目标和本地已验证backup，并明确 `update recover`；调用原rollback，不关闭降级保护。已撤回版本不再安装；更高稳定修正版优先。

运行依赖、官方jdo-cli是独立升级。依赖指纹变化暂停自动切换，安排空闲维护并复用原依赖安装器；官方CLI仍走官方来源，不因业务上游更新无条件重装。更新器不参与店铺登录/业务。

## 维护端（只在研发/维护机器）

来源配置维护于源码maintenance/upstreams.json：8个受保护组件与抽取的sufy client来源，来源仓库/稳定tag渠道或经维护选择的分支、固定采用commit、显式文件映射。新增来源/依赖先配置，不扫描任意仓库自动安装。

```text
python scripts/upstream_updates.py scan
python scripts/upstream_updates.py discover --component collection
python scripts/upstream_updates.py review <candidate.json> --note-file <实际技术审查记录>
python scripts/upstream_updates.py admit <candidate.json> --confirm MAINTENANCE_ADMIT
python scripts/publish_stable.py publish --version <递增产品版本> --notes <实际更新说明>
```

discover使用独立Git cache，对旧上游/新上游/商家源码做三方增量；识别新增/删除/重命名、依赖、授权费用/恢复/接口与数据格式变化、跨组件引用/经验变化。干净字节合并不等于语义安全；文档提内部系统只作上下文，执行源码中的渠道literal仍须实际调用路径审查。冲突留candidate/旧稳定不动。

review记录维护者对真实差异的审查，admit只纳入工作区不发布。新增工具/依赖必须先有显式映射；外层商家经验不被覆盖。候选高风险/冲突不自动发布，也不要求商家逐文件审批；技术审查由维护方处理，真正模型/费用/产品范围/权限决策集中提出。

publish生成固定包与签名稳定索引，默认还只是本地准备；维护方提交发行物/索引并推送商家仓库后才是远端发布。索引包含版本/发行ID/Git blob/大小SHA/manifest、系统宿主运行环境、组件commit、说明与撤回。签名密钥不进仓库。`publish_stable.py withdraw --release <ID> --reason ...` 准备撤回索引；`authorize-recovery --from-release ... --to-release ...` 准备受控恢复授权，均需要维护方推送。

不创建GitHub Release、不触发自动Actions、不安装系统常驻服务。上游候选、稳定发布、客户端磁盘升级、宿主加载版本是四个不同状态，分别报告，不能把“仓库已推送”说成“所有商家电脑已更新”。

维护端scan自动处理已配置上游、没变化不产生候选；本轮没有授权或安装无人定时扫描/自动GitHub Actions。可由维护方现有流程调用scan，若要定时执行需另行配置授权。semver稳定tag存在时跟踪tag渠道；本轮8个业务源未发现稳定semver tag，明确选择其分支作为候选渠道。抽取的sufy client单独发现差异，不能把整个上游文件盲换进商家核心。索引过期可用publish_stable.py renew续签并递增sequence，不覆盖旧发行物。

首次升级前仍须由宿主确认原任务空闲；此前版本尚无宿主租约，不声称能检测所有在途隐式读取。安装/切换保留经原回执验证的上一版程序快照；恢复旧任务时usage begin可带 --loaded-version <实际旧版> 使用旧代码/契约。版本字段由宿主依据实际加载内容报告，不把diskVersion推断为聊天版本。程序快照不会包含状态目录的商家数据/Key/授权。

每个商家状态根绑定一个活动安装目录；换宿主/安装位置不静默改绑定，多宿主并行需明确独立状态/迁移方案，不能覆盖另一宿主在途状态。此边界会在安装前检查，不用不明目录覆盖来伪装自动升级完成。


## 0.4.2 解释器与发版一致性

`merchant.py update`在宿主Python缺cryptography时自动切换到已准备的runtime-venv；缺依赖不是网络deferred，也不静默pip安装或登录。首次离线状态没有runtime时仍给明确环境错误。

发版必须先从最终待提交树重新构建并与固定发行ZIP逐文件、SHA256一致，再提交/推送。发行后再改入包文件必须递增VERSION，不能依赖同版本异包保护来兜底。文档/测试在包外可另提交，但不能改变registry等入包元数据而忘记重签。
