# 既有商品整版编辑与安装恢复验收（开发检查点）

2026-11-15；本轮是进展，不是整个目标完成。私有仓库 ctzlyj/heideng-ops-agent-merchant-skill，分支 codex/merchant-foundation。

- 代码提交：`c3f9dfe70ea9d26f6a43c9d5ac9dff7a1d9bdcf3`。
- 最终独立 ZIP SHA256：`ef1c513aee7061fbdd6b6aeda35f45c7a5aed938ed9163c2d4482effb6fe9aba`；0.1.0 未正式发行，56 个包文件（含 manifest）。
- fresh HOME、断开测试进程 socket、无员工依赖的 **292 项测试通过**；安装包凭据/个人路径/未知文件审核为零发现。
- 真正从 GitHub clone 指定提交，fresh venv/公开 PyPI 测试依赖，重建 SHA 完全相同，审核/安装/onboarding/完整 suite/五组独立 smoke 全通过；克隆工作树干净。不是本地 copy 回测。

## 本轮实现

`edit_contract.py` 与 `schema_edit.py` 提供来源基线、两阶段完整既有商品图片/详情编辑、原申请单与完整线上字段回查。capture 保存隐私检查后的完整原详情与模板。所有提交业务值按原模板声明绑定确切原字段；保留真实 SkuId/SkuUUid、编码/价格/库存、完整销售属性身份/census/mapping、未知 business blob，不能借另一个相等值或 caller 改写元数据伪造来源。

仅允许原图槽和明确 WareEditor/detail desc 修改，安全 HTML 在批准前规范化；同店原上传回执、成功同 body validation、600 秒与最终截止、官方同版 stdin 薄适配均不可绕过。持久基线编辑意图不因新 validation nonce 重放正式 POST。generic verification 无法代替 dedicated 全字段回查解锁；unknown 不以当前目标匹配清除。

一次有界整版独立评审的 3 项重要问题均以 RED→GREEN 修复：critical 字段 HTML 转换、销售属性 attrId/mapping/census 回查、通用 verification 提前解锁。追加边界覆盖原值缺失/错字段、重复属性、opaque 数组、nullable 原详情及无维度 SKU，不造数据。

## 实际烟测与安装排障

- 最终包 fresh-install 整版编辑：1000 个带实际标识的合成 SKU、1001 个原图槽；known 正式编辑 POST 1 次，独立 unknown 意图 POST 1 次且不重放。原申请单与线上字段回查分开；SKU 重排按实际 ID 定位；最后 SKU 库存及 attrId 漂移被拒绝。
- 新品 1000-SKU 校验/条件提交、原生模板/价格、原生素材及已审官方 0.3.7 源码的合成 auth/HTTP/signing 最终截止边界全部回归通过。
- 安装前间歇失败插桩捕获 stage→target os.replace 的 errno=13 / WinError=5。原生无 FILE_SHARE_DELETE 子文件句柄确定性复现同错误，释放后同源 rename 成功；实际占用进程未确认，不指认特定后台或杀毒软件。路径长度/state 对照未证明稳定关联，后续插桩也有连续成功，不称自然故障稳定每次重现。
- 新增 7 项安装回归，测试组先 RED 后 GREEN：仅 WinError 5/32/33 本地目录切换最多 6 次调用/1.55 秒计划退避，持续检查源 identity、目标不存在和非链接；持久失败保留 journal/备份。覆盖真实 Windows 句柄、永久/非 Windows 失败、源替换/目标出现，以及升级/回滚。**未增加店铺或模型 HTTP 请求重放**。

## 限制与下一步

上述 pending/online 字段标志仅为合成接口契约证据，不是真实京东线上生效；remotePixelsVerified=false。未执行真实 OAuth/店铺写入或模型付费生成。纯规则/未填充模板的通用填充、实际线上接口和状态语义、真实商家链路及对外分发/商用许可仍待完成，不能用 mock 或历史验收替代。

视频上游本轮重新查询为 0.3.0 / 29548089f7b71ac77ddb584caac0966a98df24ab，生成 provider 未启用；内部只读核验为 1.5.4 / 13692b759bd52e35c3670cf8fad5330e1bf2b576，工作树干净，本任务未改内部版或个人安装 Skill。

证据：native-full-edit-verification-2026-11-15.json、github-full-edit-roundtrip-2026-11-15.json。只提交脱敏汇总，不包含运行日志、官方源代码、店铺 Profile、凭据或源照片。安装提示词仍在 README.md，由 Agent 执行，商家无需手敲命令。
