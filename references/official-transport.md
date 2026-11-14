# 官方 CLI 的大载荷传输

商家仍只安装黑灯商家版一个仓库。Agent按所需能力从京麦官方公开策略校验获取CLI；运行时的官方工具与源码不打包进本仓库。不会手抄签名、导出Key/Cookie，或要求商家手动处理base64。

## 路由

- 小载荷：校验安装的官方二进制。按实际Windows commandline UTF-16长度（含JSON引用转义、路径与参数）预检。
- 超过本地24000 units安全预算：**提交前**选择`official-source-stdin`。同策略下source version、binary version和binary archive SHA必须匹配，源SHA必须在已审计清单。公开源0.3.7声明**deprecated**，不是新正式SDK；任务scope必须明确记录该状态，不能隐藏。
- 同版源仅内存加载；源与业务JSON通过stdin传给Python -I -B自有driver，OS argv只有解释器和driver路径。使用官方main/parser/cmd_invoke及签名/请求实现，不复制源码或密钥。
- Windows强制Credential Manager，独立HOME/JDO_CLI_HOME和merchant-Profile。macOS所有带凭据CLI仍禁用；不存在偷偷降级到file或security secret argv的路径。
- 本地安全上限：业务8MiB、源2MiB、stdin envelope16MiB。不是平台SKU/图片限制；超限需按业务允许方式完整分批，不能删SKU/裁数据冒称完成。

## 任务批准与恢复

`task-plan`正常返回`scope.officialExecution`，包含transport、版本、二进制SHA与archiveSHA；stdin另含sourceSHA/path/status。全部进入原fingerprint。Agent展示完整店名/venderId/Profile、写入范围和transport，取得本次批准后执行。

准备与执行前核对；源/版本/安装二进制变化不能沿用旧批准。没有officialExecution的旧prepared任务也不能由新版真实client沿用旧批准，需重新规划。耗时预检后再核店铺；worker携带完整批准店铺身份，以官方签名seller-info GET核验同一内存认证上下文，并冻结该上下文用于业务请求，防止中途替换Profile。执行后的result中`_merchantExecution`记录实际使用版本。源码撤回/策略变更或源未审计时暂停大载荷，先做空闲更新或合法新适配，不能换来源悄悄继续。

未知/空/非JSON回执、连接丢失或worker退出先查询原任务，不因换transport重提。stdin仅在提交前选定，**不存在binary错误后自动fallback**。该driver关闭上游写请求的transient及auth-marker重试；GET保留官方重试，预先OAuth刷新仍使用官方安全凭据链。批准期限进入stdin，在源初始化或凭据刷新后、实际业务HTTP前再次检查。

stdout/stderr仅在内存有界捕获；get_auth_context/refresh返回中的Key/token加入脱敏集合。原stderr、异常文本、dry-run头/签名和源码不发布；成功JSON中的完整请求/长载荷回显也去除，JSON键中的已收集秘密同样脱敏；源log_event/telemetry不执行。错误只表示原任务需核对，不提供安全重复提交结论。

## 当前证据边界

已验证：真实公开source/binary按SHA获取，同版官方parser/signing在真实隔离Python子进程处理900000字符合成base64；实际业务网络socket阻断，并用合成auth/HTTP hook验证成功、auth-marker和响应丢失各一次业务请求；独立默认协议入口在空商家HOME中拒绝且不暴露原stderr。

未验证：真实merchant Credential Manager条目读取/OAuth刷新、真实图片API、真实上新、真实店铺写入。合成base64不是已上传图片。正式发行和第三方许可另按整体验收处理，不能用本测试冒充商家上线成功。


## Deferred minor

独立评审发现worker自身没有第二次断言JDO_ENV=prod；正常parent已强制prod，未发现正常路径错环境提交。当前作为纵深防御项暂缓，不声称worker可接受任意环境；外部不要绕过本仓库parent直接启动driver。
