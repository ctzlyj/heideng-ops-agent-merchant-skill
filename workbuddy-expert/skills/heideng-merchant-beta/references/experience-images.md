# 商品图、样张与交付

商家问“上次认可的那张图”，先传 `{"arguments":["sample-context"]}`。唯一命中时展示 delivery.imagePath 指向的已接受原件、delivery.skuUrl 对应的目标规格链接和 delivery.upload 中的状态。对比图使用 delivery.comparison 标明的文件及左图归属；来源或上传情况待核的部分保留原口径。多笔候选以店、商品、规格等最少信息区分。

打样从实际商品的已核对规格中选代表图位：商品外形、颜色、规格与配件用能说明这些事实的实物参考，版式参考源轮播。宿主按当前任务自行设计。使用 `run photo-listing -- make-sample` 单独生成样张计划，按 `image-quote.json` 确认新增图位和积分。1K、2K、4K 每次计费请求分别为 3、4、5 积分；额度不足时可缩小到明确选定的图位。已交办生图时使用 `confirm-image-fee` 一次确认。商家只查看、询价或讨论意见时交付已知结果。

接受样张后以原图哈希和目标规格保留 `accept-sample` 回执。给已有商品换规格图可以从 `run images -- replace-sku-images` 做只读可行性检查，确认要改的真实 SKU，再提交并逐 SKU 读回。检查其他规格、价格与商品状态。付费请求未知时先 `reconcile-images` 核对；确需另发时说明可能重复计费，单独关联原请求。
