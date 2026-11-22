# 上新、实拍、链接复刻与矩阵

新对话交付对比图时读取样张回执里的 `comparison`。左图可来自目标链接的指定 SKU、复刻源商品或本任务指定的参考图；右图为对应哈希的样张。仅向商家展示已经核验归属的商品链接。旧样张缺少来源记录时，宿主可用 `recover-sample-comparison --package <父任务> --image-id <样张编号>` 核对已保存的商品回读与京东缩图字节，补一份本机回执。如仍无法匹配，先交付已接受原样并标明左图来源待核。商家主动提供对照图时，设计条目的 `comparisonPhoto` 可指向本任务登记的原素材。

## 适用问题与事实

商品链接搬运、本地素材上新、实拍照片上架、同款矩阵或修图后重发。需要用户选定来源和权利、实际商品事实、目标店铺、类目参考、授权品牌/必填属性、完整销售规格与SKU价格库存、已有草稿/发布回执。

不要把一张图推断成全部规格，不借品牌填空，不在尚未上架的包里编造京东商品ID/链接。资料不足只问具体缺项，其他可行整理继续。

## 判断与参考路径（可调整）

- 链接只采素材不上架，先用 [采集](experience-collection.md)，不得因素材齐全自动发布。
- 常见新商品：源资料/类目与品牌判断→真实SKU和图片→原本地包/预检→确认后的发布与回读。已有合格草稿可直接复用，不强制从采集重跑。
- 实拍：锁定真实商品外观/规格与风格参考用途，沿用 photo_listing 的包契约；图片需要修复才组合 [图文](experience-images.md)，事实不能由风格参考反向改写。
- 完整复刻：原 hot_replica_preflight→apply→hot_replica_publish，详情连续性、shared/series 判断与规格图落位复用成熟实现，不另造发布流程；宿主根据源链接画面、SKU 差异和本次目标提供完整逐图提示词。当前预检的 `--analysis-file` 接收宿主对真实图像的 drops 与 continuity {spec,pages}；page索引对应剔除后保留页，不能填假判断绕预检。
- 矩阵沿用原 matrix_listing 的差异方案与发布回执。同一店/商品/覆盖与费用已有批准，不要求每进一个模块再确认一次。

## 实拍与本店复刻的宿主操作

商家给的是本店 SPU 时，使用 `photo-listing init --shop <已核实目标> --source-spu <SPU> --package <任务包> --title <标题>`。工具从本店编辑详情提取有序 SPU 轮播、规格首图和详情，记录每张图片的来源、顺序及内容哈希。用 `.reference-cache/assets.json` 中的 `role`、`group` 和 `productPhoto` 识别各图。外部参考使用 `--reference <京东SKU链接> --photos <商家实拍>` 并运行 `reference`。外部参考仅供分析风格。无需参考的商家上新使用 `--no-reference`。

宿主查看实图、SKU 和已验证卖点，决定每张图的经营目的、版式、文案和商品事实。先做 `refresh`、`set-facts`、`questions`，核对标题 60 单位、包装三边、毛重和类目事实。缺实测包装数据时一次问清楚。复刻同一商品时先核对是否可以沿用已有 SKU 图和详情图。

商家说“第一张图”时，先核对其打开的 SKU 链接和选中的规格。对于本店复刻，`.reference-cache/assets.json` 的 `sourceSkus[源SKU编号]` 会列出该规格的候选首图 `firstImageCandidates`，包括后台规格图、对应销售属性组的轮播首图；无专属图时使用共享轮播候选。读 `entries` 可看后续轮播、用途、顺序和来源。实际打开消费者页面并核实选中规格后，可用 `record-first-view --package <包> --source-sku <编号> --url <SKU页> --product-photo <候选的productPhoto> --screenshot <首屏截图>` 保存证据。页面打不开时标明“后台候选，消费者页待核”。买家端显示顺序随商品、规格和页面而定。

在新采集的本店复刻包中，为 SKU 设计指定 `skuKey` 和原商品的 `sourceSkuId`，在 `firstImageReference` 填已比对的该原规格首图路径。通过 `photos` 选择所有能证明本图事实的实拍和同款图片，在 `identityChecks` 写可观察的身份核对要点。选择依据随商品改变，例如面料纹理与版型、印刷版本与装帧、部件组合与数量。单图已充分时可只用一张；遮挡、背面或搭配难辨时应选多角度。未能核对的细节先不作展示承诺。图位、背景、图数与文案由宿主按商品决定。

“先出一张我看看”走 `make-sample --package <原包> --image-id <图号> --image-prompts-file <设计>`。宿主挑用户指定的规格或有代表性的差异款，只为这一张报价。用返回的 `samplePackage` 走既有 `generate` 和 `review`，把回执 `sampleReview.comparison` 里的源图和样张并排交给商家。商家认可后用 `accept-sample --package <原包> --image-id <图号> --evidence <本次答复引用>`，在本规格的大货设计中填返回的 `reusePhoto`。后续报价只算还要做的图。看样过程独立保存，大货包的原计划、已发布状态和图片继续可用。

`make-plan --package <任务包> --image-prompts-file <设计.json>` 读取宿主设计。JSON 对象含 `styleObservations`（有参考时记录实际观察）和有序 `images`。每张有唯一 `id` 和 `role`（main、sku 或 detail）。要生成的图给 `prompt` 和 `photos`（包内 `sourcePhotos` 的子集），复用时给 `reusePhoto` 指向已有图片。SKU 图带 `skuKey`；详情图可带 `kind`、`skuKeys` 和 `exactVisibleText`。宿主对图片及可见文字的核对和设计由本次商品决定。工具按角色校验、保存来源与设计，将完整提示词原样交给模型。信息不全但商家只需独立主图打样时，可用 `--preview`。已上架仅修详情用 `--only detail`。

宿主用 `image-quote.json` 打开 `confirm-image-fee`；商家确认一次，由宿主把返回的回执传给 `generate --approval-file`。已有图片需重做时按报价传对应的 `--redo <图片id>`。已批准范围内继续使用剩余额度。

`accept-images` 默认记录宿主质检。商家确实审过当前预览时才用 `--reviewer merchant --evidence <商家答复引用>`。以 `verify` 的 `consumerLinks` 交付各规格商品链接；商品后台状态、消费者页面能否打开及是否有报价分别报告。

## 平台限制与工具例外

销售属性卡片/映射、类目必填字段、已授权品牌、图像分组和价格组件是当前接口契约，不是可选经验。商品目录没覆盖某新类目时，可读取官方参考并在任务目录做必要适配，不默认重造发布引擎。

重复发布保护沿用原 matrix.publish_guard/SUBMITTING，低层发品和复刻入口共享原语义。丢失响应先按原货号/申请单/回执查远端，不能换入口再发。已有商品编辑不等于可连带调整库存/价格；按实际操作范围和接口分开处理。

## 实际工具入口

- `run listing -- <jd_product_pipeline原参数>`；登记 `scripts/publish_local_draft.py` 处理已有草稿。
- `run photo-listing -- ...` / `run matrix-listing -- ...`。
- `run link-replica -- --sku <真实源SKU> --draft-root <任务草稿> --store-config <实际店铺配置> --reference <当前类目参考> --decisions <真实预检> --confirm PUBLISH_TO_JD`。
- 新资料/分析/局部脚本放商家任务目录，不写入 mature 快照。官方目录外能力仍可按 [环境](merchant-cli-environment.md) 调用。

## 完成证据与来源

生图请求结果未知时，沿原任务包执行 `reconcile-images --package <原包> [--units <图号...>]`。只读结果列出每张图的原预占、关联回执和本地产物。供应商账单缺失时显示金额未知；看到 `LOCAL_RESULT` 后用原 `generate` 恢复本地产物。确实缺图时，向商家说明哪些旧请求仍可能计费，以及追加这些图的次数与金额上限。将返回的 `replacementQuote` 交给本地费用确认入口，商家同意后由宿主执行 `generate --package <原包> --replace-unknown <获批图号...> --approval-file <新批准文件>`。每个新尝试关联原预占，历史回执归档在任务包的 `.generation/attempts/`。若新尝试也结果未知，重新从原包对账。

分别交代已生成素材/草稿、平台校验、productId/applyId、审核状态、线上SKU图片/价格/库存与关联结果。提交成功不自动算线上生效，源视频另按 [视频](experience-video.md) 处理。

来源 jingmai-hot-product-mover-skill 1.2.6 / 3ee08af；[销售属性](../mature/listing/references/structured-sale-attributes.md)、[SKU图绑定](../mature/listing/references/sku-image-group-binding.md)、[复刻经验](../mature/listing/references/jd-hot-replica-mode.md)。原历史店铺/固定日期案例只是已知条件，不能当本店数据。当前外部视频生成未配置，但不妨碍不需要AI视频的商品准备或已批准上新。

## 报价前核验能否按原规格上架

整套上新先填写当前商品的真实类目和媒体分类、各 SKU 的价格库存、属性和销售维度。宿主以 `facts.saleDimensions` 指定实际维度名称或 `sale-prop-…` 组件，`skus[].attributes` 按名称或组件编码记录逐项取值。结构化维度可逐项写 `templateValuesByAttr` 并用原 `apply-sale-templates` 组装，或使用已经核验的 `saleTemplateProps`。无销售维度商品可用一个 SKU 和空维度数组。主图同一销售属性组应复用同一组首图。

全套 `make-plan` 与发布沿用相同的商品构造和本地预检；资料或本地能力不足时先补齐，再报新增生图费用。独立打样、已有商品详情改图仍可单独交付。详情数量依本商品要说明的事实决定，可通过 `facts.requiredDetailTopics` 和逐图 `covers` 核查。平台有明确张数限制时保留相应依据。
