# 图文优化、SKU图片与整店刷新

## 适用问题与事实

现有商品主图/详情风格优化、SKU代表图/规格图落位、整店刷新、驳回图修复。需要目标店铺与商品SKU集合、素材槽位/用途、真实商品外观、当前线上图片、已批准修改范围，以及是否已有合格新图。

## 判断与建议路径

- 建议先区分“图片内容不合格”与“绑定位置不对”。后者优先用成熟更新/整版编辑，不为换落位重新出全套图或重发商品。
- 有合格本地图，可先使用原 upload/patch/verify；没有新图且任务只做审查，不要求生图Key。
- 单商品/少量槽位用 mover 的 image_patch_update/detail_repair；整店已确认范围可用原 refresh 任务链。刷新参考序列是 build_plan→download_sources→generate（确需时）→upload→patch→verify→report，不是所有任务必须跑全部步骤。
- `run image-refresh -- <任务目录> --profile <本店> --vender-id <真实ID> --shop-name <本店> --scope main|detail|both ...` 创建原任务配置；后续 `run --entry scripts/run_all.py image-refresh -- <任务目录> --steps <所需原步骤>` 或原单步入口。保持原 ledger 和已提交项恢复，不做新的黑灯任务队列。
- 透明/白底与驳回修复按 [内容](experience-materials.md) 组合。本任务范围已有批准，复用同一批准，不叠加审批。

## 经验与接口限制要分开

原模型下主图画廊按整商品/颜色第一维/SKU绑定，不能用“第二维尺码主图”经验代替接口支持；逐SKU规格图与主图画廊是不同用途。原 SkuGgtImage/mappingId/UUID与逐位置回读规则是当前源版本契约；不靠改字段名或换入口规避。

共享主图与series每款独立序列按实际源图判断；同图款式可复用来源映射。原接口遇到特定类目限制时准确报告，不推广为所有商品永久不可改。官方契约变更后可采用其他已授权当前接口，但保留同店、图片对应和未知写入保护。

LTS4AI / gpt-image-2.5 是已选生图配置，沿用原 sufy client；已有用户模型/平台选择与预算不能在“优化流程”中暗换。只在真实需生成且费用范围获准时使用商家Key；不继承上游公司多模型池。

## 完成证据、来源与限制

本地图像/规格、真实上传结果、SKU分组/槽位、审核和线上回读分别标注；重复请求不能用来消除未知状态。整店报告只覆盖实际任务集合，不用样本图片冒充全店。

来源 mover 1.2.6 / 3ee08af 与 jingmai-batch-image-refresh-skill 1.4.5 / 8a2f3df。原 [SKU绑定](../mature/listing/references/sku-image-group-binding.md)、[详情](../mature/listing/references/detail-pages.md)、[刷新配置](../mature/refresh/scripts/new_job.py)、[刷新步骤](../mature/refresh/scripts/run_all.py)。refresh 本来没有完整经验Markdown，本页只整理原脚本与已有图文经验，不宣称新增业务。
