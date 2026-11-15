# 既有商品：完整来源基线 → 图片/详情整版编辑 → 原申请单/字段回查

商家只描述目标，以下命令和 JSON 文件由宿主 Agent 生成并执行，不要求商家敲命令或手写字段。真实写入仍需明确同店、同商品、全部 SKU 和本次修改范围批准；开发验收不包含写入授权。

## 来源基线

先 `product-schema --profile <merchant-profile> --product-id <actual-id>`。capture 现在保存经隐私检查的完整原详情、模板、真实 SKU 集合和来源 SHA，前后读取须一致；旧 capture 没有完整详情不能直接升级为已证来源。

Agent 读取当前公开官方指南与实际模板，投影/填写业务 DTO，再运行：

`schema-edit-baseline --capture-id <id> --schema <local-json> --bindings <local-json> --sale-sources <local-json>`

- DTO 只含 componentCode/value/properties；已识别的规则元数据留在原 capture，不随商品 body 提交。未知 business 值完整保留；未识别的 DTO 外字段不能静默删除，会拒绝并要求查明协议。
- 全部组件、属性、SKU 行结构必须保留。SKU 第一、二位是实际 SkuId/SkuUUid，二者相等，不能用随机 UUID 代替旧 SKU。全量 census 与原详情 ID 集合必须相同。
- 每个 value/properties.value（包括整块未知 JSON）都必须有原字段绑定。binding = {schemaPointer,sourcePointer,skuId,conversion}；顶层 skuId=null，SKU 内填真实字符串 ID，sourcePointer 是该原 SKU 对象内部 RFC6901 路径，不是数组位置。conversion 仅 identity/string/html/jfs/mapping；非预期转换拒绝。
- 绑定必须对应**原模板**的 productDetailField 声明，不能把别处一个相等的值当作这个字段来源。关键 SKU 字段使用已核实原字段：skuId、outerId、priceInfo.jdPrice、stockNum。当前无法证明声明/完整结构的模板不准许整版提交；不把合成模板验收说成所有线上模板兼容。
- sale-sources 每项 {skuId,componentCode,sourcePointer}，指向原属性记录；attrId 必须对应 sale-prop-xxx。mappingId 保留原值，空时取原 attrValues，不生成新 ID。isColor 来自 capture 的实际规则元数据，冲突/未知拒绝。
- 未修改的价格、库存、规格、未知值仍须原值绑定；本轮只开放原图槽和明确 desc 修改，不用整版请求暗改其它业务值。

## 两阶段编辑

`schema-edit-validation-plan --baseline-id <id> --changes <local-json>`

changes 数组只支持：
- 图片：{pointer,assetTaskId}；pointer 来自 capture.imageTargets，素材必须是同 Profile 原已知上传回执，实时原 imgId/JFS/属性回查。
- 详情：{pointer,html,assetTaskIds}；pointer 是原 desc 属性的精确位置。HTML 在批准前安全规范化，拒绝注释/脚本/事件/任意外链；图片只能是原商品已证来源或本次明确绑定的合法上传素材。

同颜色的关联图槽须在明确范围中保持一致，不偷偷扩散修改范围。无销售属性时不编造维度，保留已证原引用与实际 SKU 身份。

分别对 validation 任务和 `schema-edit-plan --validation-task-id <id>` 返回的正式任务绑定 task-approve 后 task-execute。可以沿用用户对同一完整范围“校验并通过后提交”的一次许可，不重复追问；来源/内容/执行契约变化须重新批准。

body 是 scene/schema/productApplyDTO 扁平结构，编辑时 productApplyDTO 带**原 productId**，不会新建另一商品或删除 SKU。共用原校验成功回执 SHA、同店同 body、600 秒、最终截止时间、已审核官方 stdin 及 HTTP 不重放边界。普通 task-plan 不能绕过。

同一基线是持久编辑意图，校验 nonce 改变不允许第二次正式 POST。旧未启动编辑会被新已验证范围 superseded；已受理的旧编辑在原申请单字段证明前阻断其它写入。unknown 保留原请求未知，不以线上目标匹配或换工具重提。

## 原申请单与字段回查

- `schema-edit-status --task-id <id>`：只读原任务，不把受理当线上。
- 同命令加 `--refresh`：用原 applyId 的官方 GET 回查，原 productId、完整原 SKU 集合、全部绑定值/明确修改值都相符才 pendingFieldsVerified=true。
- `schema-edit-online --task-id <id>`：读取原 productId 与完整 SKU census，按真实 SKU ID 重新定位每行；价格/库存/规格/未知值及新图/详情都匹配才报告字段匹配，SKU 分页或任何最后一行变化均不能算完整。

当前命令的字段匹配证明有观察时点，非跨接口原子快照，也非远端像素质量检查。unknown 无原回执不能通过这些命令解锁。真实线上接口/状态语义、完整所有类目模板兼容和用户店铺实机链路仍需实际商家授权验收；离线输出不得冒充真实线上生效。


### 已强制的补充边界
关键 SKU 字段不允许 HTML/jfs 等改变业务语义的转换；未知 numeric business 值不能无声明改成 string。每次待审/字段回查重验实际 attrId、销售属性全量集合、当前 mappingId 或 attrValues fallback，不能只看一个原指针值。通用 verification/resultVerification/onlineVerification/precondition 不得附加到 schema-edit 任务；通用回查也不能释放整版待审锁。来源为 null 的详情原样保留；opaque JSON（即使包含 componentCode/key=desc）不按编辑器或 DTO 误解释。
