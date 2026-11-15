# 原生完整编辑模板与无损图片草案

这是完整发布/编辑链路的前置能力，不是已经完成上架或图片绑定。Agent自主运行，商家不用敲命令。只使用本人商家Profile，官方jdo-cli和公开校验资料，不读取员工凭据，也不调用内部模型。

## 1. 读取完整编辑模板

`product-schema --profile <verified-merchant-profile> --product-id <actual-product-id>`

先读取商品详情与完整SKU分页，核对productId、末级类目、唯一SKU集合和明确分页总量；用官方GET `/rest/sp-product/v0/product-schemas`，扁平参数 `lastCategoryId`、`scene=pop`、`productId`。返回data必须为唯一模板的JSON字符串数组。模板不经“精简”：未知控件、销售属性、所有SKU和详情全部保留。前后详情一致才保存独立capture及fingerprint；读取中途错店、源变动、不完整集合或JSON重复键均拒绝。超出当前JSON运行时可精确往返的小数/非有限数、128层以上模板及key/value结构中的敏感逻辑属性也会拒绝；不会舍入数字、删敏感字段或返回带凭据模板来凑“无损”。

`schema-capture-status --capture-id <id>` 只读取原本地证据，不刷新授权、不称为实时结果。`scope.observedAt`为观察时点；有限次重复观察不是原子数据库快照。

返回 `imageTargets` 只覆盖模板中**已有**的商品WareSkuImg/LongImg及SKU内SkuMainImage/SkuRectangleImage的imgUrl属性。没有识别的未来组件原样保留但不成为可修改槽位。case敏感，不把原子接口的wareEditor等名猜作整版WareEditor。

**SkuUUid不是已证实的真实skuId**。读取的真实SKU集合与schema行数分别提供；即使数量相等，也不能声称已经建立身份映射、模板所有必填项已填充或账户支持整版更新。`skuIdentityMappingVerified=false`、`submissionReady=false`。

## 2. 用已有合规素材生成本地草案

图片先走material-upload-plan→明确批准→execute→原回执imgId fresh回查。保存图片空间和商品绑定两回事。

`schema-image-draft --capture-id <id> --changes <local-json-file>`

changes为数组，每项只含：
- pointer：原capture.imageTargets返回的精确JSON路径；不凭产品名/SKU序号猜路径。
- assetTaskId：同一Profile/同店已知上传任务ID；不是文件名、临时URL或任意imgId。

素材原回执必须已知，任务submitted/verified时fresh回查原ID和原JFS/属性。unknown、跨店/跨Profile、元数据变化及凭据内容拒绝。复核商品/模板与capture仍一致后，只替换这些已有imgUrl，**不新增、删除、重排任何组件或SKU**；不改SkuUUid/colorId/imgRefId/orderSort、不用SKU ID伪造mappingId，详情和非目标字段原样保留。同colorId/imgRefId/位置的SKU图片组若需要替换，必须在本次显式范围中保持一致；不偷偷扩散用户范围。

`schema-draft-status --draft-id <id>` 读取指纹绑定的本地草案。草案不生成task-execute可提交的任务，不发商品写入；保存完整新schema和逐槽旧值/新值/素材回执SHA。

**返回必须保留**：phase=local-lossless-image-draft-not-submitted、submissionReady=false、productBound=false、remotePixelsVerified=false。素材存储字段fresh匹配并不证明JFS远端像素身份或已对商品生效。

## 3. 尚待完成的发布/整版编辑

真实账户schema的全部SKU身份/原值映射、所有必填控件回填、官方合规validation明确成功契约、分别批准的整版POST、原回执申请单和线上主图/详情/逐SKU图字段验证仍需补齐。此实现不能代替这些步骤，也不能把给商家一份草案说成已经优化上线。

GET不提交商品；当前商品schema接口读需本人授权，不能把需要签名和可能token刷新的`jdo-cli info`当匿名metadata，不借员工/default Profile、不切pre绕权限。高风险validation POST和正式编辑仍需单独的明确授权。

本地8MiB schema解析、1000图片slot任务/100页SKU读取预算不是平台上限；超预算保留范围并报告分段或继续读取，不截断、不冒称完整。本模块目前不支持空模板直接创建商品，不擅自创建SKU。

## 验证等级

官方公开文档契约+离线合成数据+隔离安装测试；未实测真实商家授权读取、上传/绑定、图片像素身份或整版商品提交。生成模型来源仍awaiting-owner。

## 新增严格整版编辑入口

已有草案返回 submissionReady=false 的约束保留；不能仅凭这些草案绕过新的来源证明。完整来源基线、实际 SKU 身份、同 schema 校验/批准/整版 POST 与原申请单/字段回查已接入 references/native-full-edit.md。未声明的原字段/未填充且无法证明的模板仍拒绝；真实账户全字段兼容和真实线上语义尚待验证，不能用新合成测试覆盖这些缺口。
