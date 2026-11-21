# 图文优化、SKU图片与整店刷新

## 适用问题与事实

现有商品主图/详情风格优化、SKU代表图/规格图落位、整店刷新、驳回图修复。需要目标店铺与商品SKU集合、素材槽位/用途、真实商品外观、当前线上图片、已批准修改范围，以及是否已有合格新图。

## 判断与建议路径

### 更新原链接的规格图

商家说“把这几个规格的图换掉”时，宿主直接使用 `run images -- replace-sku-images --profile <本店> --store-config <本店配置> --product-id <原SPU> --check-only`。先只读核店、检查商品当前的完整编辑模板与全部 SKU，再为需要的规格准备图片。若有原发布包可加 `--package <原包>`；只有原始成功提交和当前商品状态仍一致时才复用。原模板缺少已有商品的实际字段或真实 SKU 对应关系时，先取得完整官方编辑数据，再安排付费工作。

宿主按真实 SKU ID 生成 `{"SKU_ID":"样张或成图.jpg"}` 映射，路径相对映射文件。商家已交办更新后，用 `--images <映射.json> --confirm REPLACE_SKU_IMAGES` 替换 `--check-only`。同一文件在本店本商品按内容复用。编辑后用原 SKU ID 核对各自的目标图、未改规格，以及商品与规格的其他经营字段。平台审核或响应未明时，用同店同 SPU 的 `--reconcile` 只读恢复。后台回读与买家端实开结果分别交付。

这个入口绑定京东 POP 的 SkuGgtImage，原工具已核实的规格为 1:1、480–1500 像素；其他图位沿用各自的图位要求。[原规格图组件说明](../mature/listing/references/sku-image-group-binding.md)

- 建议先区分“图片内容不合格”与“绑定位置不对”。后者优先用成熟更新/整版编辑，不为换落位重新出全套图或重发商品。
- 有合格本地图，可先使用原 upload/patch/verify；没有新图且任务只做审查，不要求生图Key。
- 单商品/少量槽位用 mover 的 image_patch_update/detail_repair；整店已确认范围可用原 refresh 任务链。刷新参考序列是 build_plan→download_sources→generate（确需时）→upload→patch→verify→report，不是所有任务必须跑全部步骤。
- `run image-refresh -- <任务目录> --profile <本店> --vender-id <真实ID> --shop-name <本店> --scope main|detail|both ...` 创建原任务配置；后续 `run --entry scripts/run_all.py image-refresh -- <任务目录> --steps <所需原步骤>` 或原单步入口。保持原 ledger 和已提交项恢复，不做新的黑灯任务队列。
- 透明/白底与驳回修复按 [内容](experience-materials.md) 组合。本任务范围已有批准，复用同一批准，不叠加审批。

## 宿主逐图设计和增量费用

宿主先查看真实前台轮播、详情、款式分组与已确认卖点，区分需要新画、可以沿用和只需更换绑定的图片。为每个待生成图位提交完整提示词。提示词跟随本次目标和事实，商家无需设计或输入技术参数。无法核实来源时继续其余免费工作。

- 整店刷新从 `plan-batch.json` 读取图位、用途、商品及原图 URL。下载原图后，以图片 key 为键，将逐图提示词字符串写入任务目录 `host-prompts.json`。对同一张图在不同商品或主图、详情中的用途分别设计。执行 `generate.py <run> --quote-only` 可读取报价，也可用 `--image-prompts-file` 指定该 JSON。
- 矩阵任务以 `matrix_listing.py snapshot` 取得真实 `material.mainImages`。将沿用的 stem 放入 `variants.json` 的 `keep` 数组，将要生成的逐图设计写为 `variants.<variant>.prompts.<stem>`。运行 `generate --run <run> --variant <v> --quote-only` 查看增量。复刻上新使用 [复刻模式](../mature/listing/references/jd-hot-replica-mode.md) 的来源清单。
- 用 `image-quote.json` 打开本机 `confirm-image-fee`，商家查看张数、用途、次数及费用上限后确认。宿主把输出传给 `--fee-approval-file`；继续原进度时复用对应回执。详见[执行策略](execution-policy.md)。

## 经验与接口限制要分开

原模型下主图画廊按整商品/颜色第一维/SKU绑定，不能用“第二维尺码主图”经验代替接口支持；逐SKU规格图与主图画廊是不同用途。原 SkuGgtImage/mappingId/UUID与逐位置回读规则是当前源版本契约；不靠改字段名或换入口规避。

共享主图与series每款独立序列按实际源图判断；同图款式可复用来源映射。原接口遇到特定类目限制时准确报告，不推广为所有商品永久不可改。官方契约变更后可采用其他已授权当前接口，但保留同店、图片对应和未知写入保护。

LTS4AI / gpt-image-2.5 是已选生图配置，沿用原 sufy client；已有用户模型/平台选择与预算不能在“优化流程”中暗换。只在真实需生成且费用范围获准时使用商家Key；不继承上游公司多模型池。

## 完成证据、来源与限制

本地图像/规格、真实上传结果、SKU分组/槽位、审核和线上回读分别标注；重复请求不能用来消除未知状态。整店报告只覆盖实际任务集合，不用样本图片冒充全店。

来源 mover 1.2.6 / 3ee08af 与 jingmai-batch-image-refresh-skill 1.4.5 / 8a2f3df。原 [SKU绑定](../mature/listing/references/sku-image-group-binding.md)、[详情](../mature/listing/references/detail-pages.md)、[刷新配置](../mature/refresh/scripts/new_job.py)、[刷新步骤](../mature/refresh/scripts/run_all.py)。refresh 本来没有完整经验Markdown，本页只整理原脚本与已有图文经验，不宣称新增业务。
