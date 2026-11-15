# 全 SKU 编辑模板与大范围价格规划

## 设计与本轮范围
沿用已批准的自主实施，继续同一独立工作区和私有分支。实施本人执行，最后只做一次有界独立评审。真实授权、店铺写入、外部付费生成不在本轮范围。

官方资料有 GET product-schemas 的 productId/lastCategoryId/scene=pop，以及 data 字符串数组；但没有足够证据证明编辑模板的 SkuUUid 是真实 skuId，或整版提交后的图片字段回查。不得将草案生成说成提交/绑定成功。

### 任务1：完整原生编辑模板
新增 heideng_merchant/product_schema.py，ProductSchemaService.capture_edit(profile, product_id)。用既有官方只读调用及身份检查，查询真实商品详情、完整 SKU 分页和编辑 schema。前后详情哈希一致、SKU 集合相同且分页 total 明确后保存商家独立 capture，指纹覆盖完整 schema/身份/证据。不猜全量模板已填充，不凭 UUID 映射 SKU。原始模板与未知组件完整保存；多模板、重复 JSON 键、非法数字、源变动和不完整 SKU 均拒绝。
测试 test_product_schema.py：平铺 GET 参数/只读/完整保存、未知组件、SKU census 不完整/错商品/源变动、多个模板/重复键、身份中途变化和 capture 篡改。

### 任务2：只改已有图片槽位的无损草案
ProductSchemaService.draft_images(capture_id, changes)，每项 pointer + assetTaskId。pointer 仅来自模板中已存在的 WareSkuImg、LongImg、SkuMainImage、SkuRectangleImage 的 imgUrl 属性，禁止创建/删除/重排和修改 UUID/colorId/imgRefId。素材必须同 Profile/同店、原回执 ID fresh readback；unknown 和 metadata 改动拒绝。只替换选定 imgUrl，保留全部 SKU、详情、其他属性和模板控件。明确 submissionReady=false、productBound=false、remotePixelsVerified=false；不会生成可直接 task-execute 的业务任务。缺全版 SKU 身份映射及 pending/online 图片验证契约继续保留为待完成项，不能清单缩减为仅主图。
测试：主图+两 SKU 的选择、未知字段/所有 SKU/详情保留、越界/重复 pointer、源变动、跨店/unknown/回执改动拒绝、不 POST。
CLI product-schema、schema-image-draft；references/native-product-schema.md 和 registry 接入且明确草案不是上线功能。

### 任务3：修复大范围价格规划
产品价规划已有官方 stdin transport；旧 18000 字符 guard 与128 verification fields/65536 bytes 不相容。去掉旧 argv guard，统一由官方 transport 的实际 Windows argv 和8MiB业务预算决定；verification 扩为明确本地1024字段/256KiB预算。原1000条 price scope 仍是本地有界任务、不是平台 SKU 上限；超限明确要求分段保留完整范围，不截断。
测试 test_large_prices.py：1000个真实合成SKU价完整批准/提交/待审/线上；最后一个SKU漂移拒绝；unknown不重放；超过本地范围不截断；使用实际 transport_for 证明大scope选择stdin。既有128字段语义回归更新为1024本地字段预算。

## 验收
每项先观察 RED 再最小实现 GREEN；clean venv/fresh HOME/禁socket全套，安装包审核及真实GitHub再克隆重建/安装后新功能回测。按测试→本地→分发审核→私有push执行。当前0.1.0只开发候选，不创建同版正式发行。

## Review Focus
- 编辑模板身份与SKU集合仅有限次观察，不冒称原子快照或真实schema SKU映射。
- 大SKU价必须完整旧价、待审/线上证据，不只测第一行。
- 精确pointer仅imgUrl值，不能越过组件/重复key冲突，全部非目标字段字节语义保留。
- 素材fresh回查只是存储字段身份，不等于远端像素身份。
- 拒绝错误不得把完整 schema/HTML/凭据输出在异常中。
