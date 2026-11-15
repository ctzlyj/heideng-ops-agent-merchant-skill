# 原生新品：完整资料 → 官方校验 → 条件提交

商家只描述目标；命令由Agent在商家独立安装根目录运行。这里是新品流水线，不把已有编辑schema的UUID猜成新SKU或删除旧SKU。真实店铺写入需具体范围批准，开发验收不是实际上架。

## 取合法数据，不猜ID

- publish-categories --profile <verified-profile> [--ids <json-file>]：实时查本商家类目，默认sceneType=3/categoryIdList=[0]。数组是原生真数组，结果不要冒称完整店铺所有分类层级。
- publish-brands --profile <profile> --category-id <actual-id> [--name <up-to-10-chars>] [--max-pages 100 --start-page 1]：先从实际parentCategoryId找到三级类目再查品牌（queryType=2/authStatus=2/pageSize=20），返回全部已读结果、total/complete/nextPage。输入品牌全名超过接口搜索长度时可查全名单，不截掉客户原品牌名或用空壳当完整授权清单。
- publish-context --profile <profile> --category-id <actual-leaf-id> --brand-id <actual-brand-id>：实际叶类目须leafFlag/selectableFlag为true；新建product-schemas只传lastCategoryId/scene=pop，不传productId。结构化销售属性才查询sale-attr-templates，路径categoryId通过params参与官方签名；保留templateData/valueRules JSON字符串，不改成伪字段。

所有读取校验Profile和店铺身份，不借员工/default授权、不切pre绕权限。实际schema和平台字段变化需按本次官方协议核对，不依赖内部JoySpace/SSO。official-doc能取得公开SHA校验指南（01组件/02类目属性/03销售属性/04图片/05与07 POP示例），Agent按实时规则填写，不需要商家手敲ID或JSON。

## 准备全部SKU与真实素材

prepare-listing保留完整sourceProduct、全部skus与本地照片，不因无销售属性的单SKU编造“默认规格”。图片先真实解码并按独立素材流程上传，原已知回执ID fresh回查。host逐图确认商品身份和质量后将该图片visualReview记为passed，图片SHA仍须匹配实际文件。不能把待审或未看图片的pending直接说成passed。

Agent按本次完整模板及devTips填写最终schema组件数组（不是带inputType/childrenComponents的规则树）。每SKU使用新唯一SkuUUid UUID、SkuVendorSku=原merchantCode，价格/库存严格保留。VenderCategoryValue的每个原规格都有来源映射；spec_map为sale-prop组件code→原skus.specs键，不省任何维度。attrValueAlias保留真实规格文字；mappingId新建时可按官方规则生成UUID，同一属性相同alias同ID、不同alias不同ID，index来自实际extra.dim。POP色图引用该颜色mappingId，不拿SKU ID猜colorId/imgRefId。

asset_bindings为数组，每项{localPath,taskId}，分别指向原manifest图片路径和同Profile原已知上传任务。全部schema.imgUrl与商详desc中的图片必须来自这些上传回执；商详用原图地址https://img14.360buyimg.com/imgzone/<jfs>，不得带脚本/事件/任意外链。图片存储字段匹配不是远端像素SHA或已经绑定商品。其它控件/类目属性/单位、物流和各类必填值由host按实际模板填写，原运输/时效/Spu ID不得漏填/改写；本地检查不冒称替代平台全部业务规则。

## 校验与真正提交（两步精确范围）

1. publish-validation-plan --profile --manifest <path> --schema <json> --spec-map <json> --asset-bindings <json>。只读取、前检和保存任务；不会POST。全SKU/原图/源商品fingerprint、当前授权和模板都进入范围。
2. 一次向用户展示店名/venderId/Profile、一个新商品及全部SKU、实际完整schema/字段来源、两步骤接口、图片来源和风险。若用户明确允许“校验并在通过时提交此同一范围”，Agent可以为两个实际任务分别绑定fingerprint而不重复追问相同内容；范围、执行代码或来源变化须重新批准。开发授权不替代本次真实写入批准。
3. task-approve后task-execute校验POST。按公开文档明确success:true且无违规报告处理；已知违规=validation-failed，陌生report=validation-unproven，超时=unknown，三者均不能发布。无数据/空对象/空列表的明确成功不误报缺回执。publish-validation-status只读本地原结果，不重复POST。
4. publish-plan --validation-task-id <original-id>：共享任务边界强制校验原成功回执SHA、同店/同body/600秒内、完整sourceProduct和当前原图/模板/品牌仍相同。随后新任务task-approve/task-execute才POST product-applies，body只含scene/schema/productApplyDTO（无request外层）。task-plan不能绕过这条已知高风险接口的先验校验。
5. publish-status --task-id：仅承认原返回applyId/productId；不制造商品URL。受理、审核、线上全SKU/图片生效不同，目前onlineEffective/allSkuOnlineVerified/productImagesOnlineVerified都为false；完整后续线上字段验证仍需补齐。

同店同源包只允许一个创建请求，换校验nonce也不会重复创建；新的校验只会替代旧未启动范围，旧批准失效。真正要创建另一份同款/矩阵商品须建立新的明确源包和写入范围。unknown保持原请求未知，不因目标值匹配、换Profile/工具/nonce重提。已知创建回执是已受理，不等于线上；不把它与未知提交一同永远阻塞其它合法任务。

## 验收与限制

目前为当前官方公开文档契约、合成店铺/数据、隔离安装测试等级。未实测真实商家授权、新品校验/创建、全线上SKU和主图/详情效果，不是正式发行或收费许可。原图byte来源、模板和所有SKU核心字段前检有强制代码，不意味着所有特殊类目规则已经本地编译；host仍需真实平台校验。整版编辑、现有商品图片绑定、原线上字段全量验收以及视频上传/绑定是后续完整目标，不能用此新品提交替代。生成模型来源仍awaiting-owner，不调用公司网关。


## 最终安全边界

- 所有认可的校验 envelope 都检查完才判定 passed；任一层非空违规报告阻断，陌生业务字段为 unproven。官方 `_merchantExecution` 仅在根层与批准的执行契约相符时接受。
- 商详仅接受 div/p/span/br/img 和有限属性；拒绝注释、声明、PI、错配标签。host 在生成任务范围前重构/转义成规范 HTML，校验与提交用同一 body；直接 task 路径不能绕过规范化检查。
- prepare-listing 首次保存随机 publication.intentId。复制/移动须原样保留；校验 nonce 与创建意图不同。同物理店铺按持久意图（兼顾原路径）去重，旧未启动发布被 superseded。真正新建的另一商品包获得新意图；旧包缺少意图不得补写后直接冒充已验证范围，需重新准备。
- 全部前检后再次校验原回执时限。传输截止时间取批准 expiresAt 和原 validation.finishedAt + 600 秒的较小值。新品发布及校验 POST 不论载荷大小都走 SHA 审核的官方源 stdin；worker 在签名后、官方网络入口和每次底层 HTTP launch 前再次检查，过期不发业务请求；TLS fallback 也不能第二次启动业务 HTTP。已知官方二进制不作同等内部时限保证。
- 去重基于本机同一商家 state 的持久日志，不声称跨机器/日志丢失的全局恰好一次语义；商家迁移须同时保留日志，不重复未知请求。
