# 原生模板自动编译验收（私有开发检查点）

2026-11-15；本轮为实质进展，整体目标未完成、没有正式公开发行。仓库 ctzlyj/heideng-ops-agent-merchant-skill，分支 codex/merchant-foundation。

- 代码提交：`e64b611bdac779c37a09e80c7da7fda7ed8d8289`。
- 独立 ZIP SHA256：`9dc68602fcbb72ddb6a98370b28c178131bacae926e747e6580205bc3562ff1d`；0.1.0 未发行，58 个包文件（含 manifest），审核零凭据/个人路径/未知文件发现。
- **322 项 fresh HOME/测试进程禁 socket 测试通过**；新增 30 项模板/来源回归。
- 真正从 GitHub clone 指定代码提交，fresh venv/公开 PyPI 依赖，重建 SHA 相同，审核、安装、onboarding、完整套件和六组安装后 smoke 全通过；克隆工作树干净。

## 已补齐的上手链路

Agent 从同店实际捕获的完整原详情与原规则运行 schema-edit-prepare，无需商家或宿主逐项手写全部 schema/bindings/sale-sources。primitive 字段使用原声明，规则 childrenComponents/空 SKU value 展开为全原 SKU，已有填值记录按真实 ID/原顺序核对；图片、详情、普通/销售属性和 unknown business 值/属性完整保留。编译本身不调用模型、不提交店铺写入。

原 capture 不覆盖。派生 capture 保留原模板、原 capture ID/fingerprint、编译器源码与源/输出/绑定哈希；读取时重算并核对原记录。rawSchema 不能无证明地变成替代原模板检查的别名。boolean 不等于数字/版本，字典顺序不改变编译结果；重复自动准备使用同一持久基线编辑意图，不因新 validation nonce 重放正式 POST。原 validation/批准/600 秒/最终截止/stdin/unknown 与全字段回查继续沿用。

## 实际开发证据

匿名京麦公开策略本轮核验仍为 0.3.7；主指南、01/03 组件与属性、05 结构化示例均按官方清单 SHA 校验，不运行会刷新 token 的 authenticated info，不切 pre。开发销售源路径是合成 saleAttrs，实际业务使用原模板声明；不称已实测真实商家 SDK 数据。

一次有界独立评审的三项具体问题均先 RED 再修复：双层规则原型替换已填 business 子属性、缺组件漏原属性 census、子 value 丢派生声明。现保留填值 children 并核对定义，原属性必须被实际组完整覆盖，保留子 value 的来源声明；补测多图定义逐位置核对与销售额外属性保留。官方 goodsAttrInfos 对应普通 SKU 属性/prop-sku，不能因有属性数组就造销售维度；共享属性定义映射真实 attrId，空/无维度不造值。

安装后自动流程使用 **1000 个带实际标识的合成 SKU**，原规则模板 SKU 行数为 0，自动 materialize 出 1000 行及 1001 图槽；无手写 schema/bindings/sale-sources。2 次合成 validation、1 次正式编辑受理，同基线/新 nonce 不再提交；原 capture 仍是原规则。申请单与线上字段分开，SKU 重排按真实 ID 核对，最后原 SKU 库存漂移拒绝；remotePixelsVerified=false。

同时回归旧全 SKU 整版编辑、新品、原生模板/价格、原素材及真实已审官方源码的合成 auth/signing/native HTTP 最终截止边界。首个自动 smoke 因测试误用命令名停在写入前，真实 parser 核对后改 schema-capture-status；确认原柄终态后重跑，不是生产请求重放。

## 不冒称完成的缺口

health-infos 是健康分，未证明等同京麦商品信息分 commodity-score；已纠正 README/Skill/registry 说明。普通图片空间保存、主图编辑不能替代信息分专属素材槽位绑定，该实际来源和完整绑定流程仍待补齐。无声明/未核实协议的类目字段须继续查真实证据及适配，不删除未知值或要求商家手填 JSON，不用 synthetic 模板宣称全线上兼容。

未执行真实商家授权/店铺写入/外部模型付费。实际平台状态语义、商家链路及对外分发/商用权利仍待验收。视频上游本轮重新核验 0.3.0 / 29548089f7b71ac77ddb584caac0966a98df24ab，provider 未启用；内部只读核验 1.5.4 / 13692b759bd52e35c3670cf8fad5330e1bf2b576，工作树干净且未修改。

证据为 native-template-compile-verification-2026-11-15.json 与 github-template-compile-roundtrip-2026-11-15.json；只提交脱敏汇总，不提交源商品/官方源码/运行日志/Profile/凭据。安装提示词仍在 README，由 Agent 执行，私有仓库需读取权限。
