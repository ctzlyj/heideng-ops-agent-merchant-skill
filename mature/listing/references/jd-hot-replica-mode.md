# 京东爆款复刻模式（2026-09-27）

## 模式定义

核对商家交办的目标店铺和源链接，读取该商品的真实规格、图片和图位，按可用素材与本次目标制定增量生成计划。

表格给出的每个来源都要在交付里有去向。按完整 SKU/SPU 和原回执识别同一商品，疑似同款保留为待核。草稿、试发或整批发布的范围以本次交办为准。目标店的类目和品牌权限按当期回执核对。

## 类目与品牌预检（先过滤，再消耗生图）

- 以草稿里的实际品牌核目标类目的授权品牌。有品牌商品核其品牌 ID；无品牌商品核 `-1` 是否可选。查不到时先查目标店授权与原商品品牌资料，保留已做好的草稿。这个预检用于避免给无法照原品牌发布的商品花费生图额度。

## 宿主设计图组

从原商品有序轮播、各规格图和详情页核对展示顺序、顾客能看出的商品特征、已有卖点和图片权利范围。让宿主依据本件商品和任务目标决定每张图传达什么。需要保留的商品身份、卖点文字与详情衔接由宿主写入相应提示词。

`hot_replica_preflight.py --sku <源SKU> --reference <目标类目> --analysis-file <本次视觉分析>` 输出图位清单 `design-input-<SKU>.json`。宿主补足各 imageKey 的完整提示词，使用 `--image-prompts-file <逐图设计.json>` 重跑预检。可复用的原素材由宿主在设计文件中标记对象 `{"reuse": true}`，仅在已核验权属且符合目标时使用。每个可复用项直接映射原图，省去模型请求。

`company_jpeg_edits.py --draft <草稿> --plan <work>/remake-plan-<SKU>.json --output <work> --store-config <店铺配置> --dry-run` 仅给出生成清单和报价。获准后去除 `--dry-run` 并提供 `--fee-approval-file`。模型请求使用对应图位的真实原图及完整宿主提示词。结果未知时保留原回执。宿主依照原图、商品事实和目标检查生成结果，再按批准范围上传。

## 发布

- 沿用现有京东来源链路：`jd_product_mover.py`/`jd_product_pipeline.py` 采集建稿，单链接正式链路用 Skill 参数化脚本（2026-10-08 由实战验证的任务局部脚本转正，去除单店特化、保留三要素身份核对）：
  1. `hot_replica_preflight.py --sku <源SKU> --reference <reference>`：检查品牌、取宿主详情衔接分析和本次逐图设计；
  2. 使用上节的 `company_jpeg_edits.py` 报价并执行。
  3. `hot_replica_apply.py --sku <源SKU>`：弹性落位（listing 改指 重制-固定 输出）；
  4. `hot_replica_price_plan.py --sku <源SKU> --competitor-ratio <源价→竞品到手比率>`：`component_source_plan` 定价；
  5. `hot_replica_publish.py --sku <源SKU> --store-config <店铺配置> --reference <reference> --decisions <预检决策> --confirm PUBLISH_TO_JD`：身份核对 → 上传/校验/发布/回查 → 代表图+规格图整版编辑 → 视频自动绑定。
  work 目录默认 `<草稿>/hot-replica/`，产物随草稿可断点恢复；`deferred_publish_batch.py` 幂等对账仅用于写结果不明的回执核对。
- 图片落位先判模式（2026-10-09，根因：100165442873 是系列品，旧链路把入口款式的 5 图序列套给全部 7 款）：`hot_replica_mode.style_image_mode(source)` 逐 SKU 读取源页 `item.image`，比较各款式 pos2 之后的场景序列——全部相同为 shared，至少两个不同为 series。
- **shared 模式**：公共池 sort1 是卖点首图；每款式组 `[公共主图@1-8 + 款式代表图@9]`，SKU 缩略图=卖点首图，代表图只放末位；第 10 槽由服务端补位，不主动写。
- **series 模式**：公共池保留重制公共主图；每款式组提交 `[该款 SKU 规格图重制版@1 + 该款专属场景图重制版@2..N]`，禁止把入口款式的场景序列套给其他款式。同源场景图按 URL 去重复用，入口款与公共主图相同的场景直接复用 `SPU-MAIN-*`，不重复消耗生图额度；发布后 `series_image_binding_report()` 逐款逐位比对线上 `material.mainImages`，并要求各款序列互不相同（服务端复制首图的 N+1 补位尾槽可接受）。
- 两种模式都**逐 SKU 规格图写入 `SkuGgtImage`**（imgRefId=该 SKU 的 uuid/skuId，规格图=该 SKU 原图的宿主逐图重制结果）。编辑场景 colorId/imgRefId 必须用 VenderCategoryValue 卡片的 mappingId（UUID）；原子 PATCH 的落位陷阱与恢复流程见 `references/sku-image-group-binding.md`。
- 多款式共用源图（采集按内容去重，多个 SKU 映射同一张标注图）时，代表图按源图映射复用：同图的款式共用同一张去标注代表图，不必逐款式重复生成（2026-09-28 10 款式金属纸巾盒验证）。
- 每次京麦写操作前 `A.identity()` 三要素核对（店铺名+venderId+Profile 完全一致），禁止 default Profile；其余 6 店 venderId 首次使用时用京麦 CLI 实时查询核对，禁止按店名猜。
- 正式发布需显式确认字符串 `PUBLISH_TO_JD`；线上补丁先 dry-run 再 apply；写结果不明只 reconcile 不重放（写回执核对是安全机制，不属于已移除的回查清单）。
- 规格图绑定回查必须读**提交的编辑体**（`SkuGgtImage` 数量 + imgRefId 与线上 skuId 匹配 + 非空 imgUrl），不能读 apply-detail 的 `material.ggtImages`——平台回显恒为空，读它会永远显示 0/N（2026-10-08 实证：`hot_replica_publish.py: ggt_binding_report()`，10126138878004 实测 11/11）。
- 原链接视频可照搬（`automate_main_video` 幂等绑定并逐 SKU 回查），平台限制 5–90 秒；超长源视频（如 141 秒）裁前 90 秒副本再上传，原文件保留。已有 SKU 绑定其他视频时停止，不覆盖。
- 用户自行下架的商品不代为上架；不动用户正在用的浏览器标签。

## 泡澡桶批次的定价算例（2026-09-28）

以下折扣、补贴、目标价差和供货背景只属于该批次。其他商品用当次交办的价格目标、活动及优惠条件。自家两店原价复制直接保留各 SKU 原价。

- 基准：**竞品（源链接同款 SKU）到手价，我方在其基础上降低 3%**。竞品到手价按源 SKU 京东价 ×（1−竞品补贴率）取（表格"到手价"列优先；无表时用源商品标签推补贴率，如焕新补贴 15%，锚点 288→244.8 已验证）。
- 竞品到手价表格行"到手价=价格"（无补贴）时，逐 SKU 竞品到手价 = 该 SKU `sourcePrice`（2026-09-28 欧式金属纸巾盒 59.8/108 两档验证）。
- 目标到手价 `T = 竞品到手 × 0.97`，逐 SKU 按 `listing.json` 的 `sourcePrice` 映射，不得按尺码猜阶梯。
- 反推京东价满足：`Jd − round(Jd×0.15, 2) − round(Jd×0.85×0.15, 2) = T`（直降 15% + 国补 Jd×85%×15%，均为默认配置活动）。**必须直接调用 `scripts/source_pricing.py:component_source_plan`（Decimal 逐项取整）计算并写入价格 plan，禁止自写浮点求解**（2026-09-28 实测：浮点 round 与 Decimal half-up 在 12.045 处差 1 分，80.29 vs 80.30，被 upload/preflight 拦截）。
- 逐 SKU 写 `SkuJdprice` 随整版编辑提交；线上生效后逐 SKU 复核 `jdPrice` 与反算到手价，40/40 需全对。锚点示例：源 288 → 竞品到手 244.8 → 我方到手 237.46 → 京东价 328.66。

## 执行方式

新店铺/新类目按 `references/adapting-new-category.md` 小规模单商品 MVP 验证，不直接套旧 Schema；跑通后按手册顺序批量执行。全链路记录各阶段耗时、失败与恢复证据。
