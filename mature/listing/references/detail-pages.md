# 详情页：方案、门槛、回读与补救（1.2.2）

适用于所有会**创建新商品**的路线。用户只说“上架”，不需要提醒详情页、也不需要写详情提示词。

## 为什么有这份规则

1.2.1 之前实拍上新只规划 3 个详情模块并拼成 1 张长图，`verify` 只检查详情 URL 存在；平台校验 0 违规就误报“上架完成”，详情页实际只有 1 张图。1.2.2 把详情页变成“先出方案、再生图、发布前强制门槛、发布后 PC/mobile 回读”的闭环。

## 一、宿主设计详情页

宿主先核实商品、每个 SKU 的差异、卖点和本次经营目标，分配可沿用的图片与新增图位。按实图设计每张的构图与文字，使用 `photo_listing.py make-plan --image-prompts-file <设计.json>` 将完整设计写入任务包。宿主可在 `images` 中用 `kind` 描述本商品的模块，用 `skuKeys` 标明适用规格，用 `exactVisibleText` 记录画面允许出现的文案。工具保留顺序、校验范围与事实，新增收费张数随复用情况计算。

## 二、禁止内容

价格、促销、折扣、秒杀、榜单、销量排名、优惠券、来源店铺名、他牌名称与标识、水印、二维码、未经证实的认证/功效/材质/尺寸/承重。参考链接的风格摘要若含这些内容（或 `reference.bannedTerms` 里登记的来源店铺/他牌词）会被拒绝，请改写成纯版式、配色、卖点结构描述。外店参考原图只在 `.reference-cache` 做风格分析：不作为生成输入；其 sha256 与任何待上传详情图相同则拒绝；路径位于缓存目录则拒绝。

## 三、发布前强制门槛 `detail_pages.check_detail_set`

在 `accept-images`、`prepare`（上传前）、`build_listing` 三处强制：

1. 详情至少有一张可交付图片，实际张数按类目要求和商品需要说明的内容确定；与 `detail-plan.json` 的模块 id 与顺序一致。
2. 新方案按宿主的逐图计划校验顺序、文件与覆盖规格；旧任务继续校验原模块清单。
3. 来源、商品事实及画面文字可核对。
4. 宽度只能 750 或 790；必须竖版；文件可读；sha256 与记录一致。
5. 无重复（字节相同或感知哈希近似）；无参考原图。
6. 画面文字抽检：无促销/价格/他牌词，数字必须在已确认事实里。

任一不过：**禁止发布**，先补生成（`make-plan --only detail --image-prompts-file <设计.json>`、`generate`，只重做详情，不动已有主图/SKU 图），不是只给警告。

宿主可在 `facts.requiredDetailTopics` 记录当前商品确需说明的事项，逐张在设计的 `covers` 指明回答了哪些。比如简单耗材的适用型号与更换步骤可以用一到两张说明；组合装可用多张解释各 SKU 配件。计划报告具体缺失的事项。平台给出更高下限时沿用 `facts.detailPolicy` 的来源、原因与最低张数。旧任务保留其明确政策。

链接搬运、模板导入和同款矩阵可沿用已核验的合格详情；仍检查来源、重复、图序及 PC/mobile 回读。

## 四、确认清单

`review` 生成 `确认清单.md` 与 `preview.html`，包含：详情总图数、模块列表（id｜职责｜覆盖 SKU）、门槛结论、`详情图/详情页总览.jpg`（仅预览，不上传）。用户在预览里可要求重做某一张：`generate --redo detail-03-skuoptions`。

## 五、发布与回读

提交体的 `WareEditor` 同时写入 PC（`userAgent=pc`）和手机端（`userAgent=mobile`），两端同一批图、同顺序。`verify` 读 `productDetailDesc.desc` 与 `mobileDesc`，逐一校验数量与 URL 顺序，另重跑本地门槛。结果写入 `manifest.deliveryChecks`：

- `platformValidationPassed` 平台校验无强违规
- `productOnSale` 商品与全部 SKU 在架/启用
- `detailQualityPassed` 详情数量/顺序（PC+mobile）及本地门槛
- `videoBound` 主图视频已绑定并审核通过（来自 `manifest.video.binding`）

`statement` 字段是唯一允许对外使用的完成措辞：任一前三项失败 → “上架未完成：… 未通过”；前三项通过但视频未绑 → “上架完成（主图视频尚未绑定，不能称全部完成）”；四项都通过才是“全部完成”。`manifest.detailPlan` 记录模块数、每模块路径/SKU/线上 URL 与回读结果，供视频和信息分 Skill 只读。

## 六、detail-repair（已上架但详情不完整）

```text
python scripts/detail_repair.py plan     --package <listing-package>
python scripts/detail_repair.py generate --package <listing-package>      # 公司三款 GPT 模型并发出图
python scripts/detail_repair.py review   --package <listing-package>      # 出预览与摘要，给用户看
python scripts/detail_repair.py apply    --package <listing-package> --confirm DETAIL_PATCH --review-digest <摘要>
python scripts/detail_repair.py reconcile --package <listing-package>     # 结果不明时只回查
```

- 只读 listing-package（需有 `productId`、店铺 Profile/venderId/店名，写前复核）；只重做详情，复用事实与全部 SKU。
- 写入体只含 `WareEditor`（PC + mobile）一个 patch 项：不含价格、库存、SKU、主图、视频字段；图片上传台账复用 `.publish/uploads.json`，同一内容不重复上传。
- 防重复：写前记 `SUBMITTING`，异常记 `UNKNOWN`；之后任何 `apply/reconcile` 只回读远端，已更新则标成功，未更新也**不重发**，要求人工核对；摘要变化（用户改了图）才允许新一轮。
- 回读不过（PC/mobile 数量或顺序不一致）→ `detailQualityPassed=false`，不得称完成。
