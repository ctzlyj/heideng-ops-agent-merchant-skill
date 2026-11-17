# 上新、实拍、链接复刻与矩阵

## 适用问题与事实

商品链接搬运、本地素材上新、实拍照片上架、同款矩阵或修图后重发。需要用户选定来源和权利、实际商品事实、目标店铺、类目参考、授权品牌/必填属性、完整销售规格与SKU价格库存、已有草稿/发布回执。

不要把一张图推断成全部规格，不借品牌填空，不在尚未上架的包里编造京东商品ID/链接。资料不足只问具体缺项，其他可行整理继续。

## 判断与参考路径（可调整）

- 链接只采素材不上架，先用 [采集](experience-collection.md)，不得因素材齐全自动发布。
- 常见新商品：源资料/类目与品牌判断→真实SKU和图片→原本地包/预检→确认后的发布与回读。已有合格草稿可直接复用，不强制从采集重跑。
- 实拍：锁定真实商品外观/规格与风格参考用途，沿用 photo_listing 的包契约；图片需要修复才组合 [图文](experience-images.md)，事实不能由风格参考反向改写。
- 完整复刻：原 hot_replica_preflight→apply→hot_replica_publish，原动态提示词、详情连续性、shared/series 判断与规格图落位不重写。当前预检的 `--analysis-file` 接收宿主对真实图像的 drops 与 continuity {spec,pages}；page索引对应剔除后保留页，不能填假判断绕预检。
- 矩阵沿用原 matrix_listing 的差异方案与发布回执。同一店/商品/覆盖与费用已有批准，不要求每进一个模块再确认一次。

## 平台限制与工具例外

销售属性卡片/映射、类目必填字段、已授权品牌、图像分组和价格组件是当前接口契约，不是可选经验。商品目录没覆盖某新类目时，可读取官方参考并在任务目录做必要适配，不默认重造发布引擎。

重复发布保护沿用原 matrix.publish_guard/SUBMITTING，低层发品和复刻入口共享原语义。丢失响应先按原货号/申请单/回执查远端，不能换入口再发。已有商品编辑不等于可连带调整库存/价格；按实际操作范围和接口分开处理。

## 实际工具入口

- `run listing -- <jd_product_pipeline原参数>`；登记 `scripts/publish_local_draft.py` 处理已有草稿。
- `run photo-listing -- ...` / `run matrix-listing -- ...`。
- `run link-replica -- --sku <真实源SKU> --draft-root <任务草稿> --store-config <实际店铺配置> --reference <当前类目参考> --decisions <真实预检> --confirm PUBLISH_TO_JD`。
- 新资料/分析/局部脚本放商家任务目录，不写入 mature 快照。官方目录外能力仍可按 [环境](merchant-cli-environment.md) 调用。

## 完成证据与来源

分别交代已生成素材/草稿、平台校验、productId/applyId、审核状态、线上SKU图片/价格/库存与关联结果。提交成功不自动算线上生效，源视频另按 [视频](experience-video.md) 处理。

来源 jingmai-hot-product-mover-skill 1.2.6 / 3ee08af；[销售属性](../mature/listing/references/structured-sale-attributes.md)、[SKU图绑定](../mature/listing/references/sku-image-group-binding.md)、[复刻经验](../mature/listing/references/jd-hot-replica-mode.md)。原历史店铺/固定日期案例只是已知条件，不能当本店数据。当前外部视频生成未配置，但不妨碍不需要AI视频的商品准备或已批准上新。
