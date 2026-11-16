# 京麦批量图选型与可靠回执（2026-10-28）

缺透明且白底通过：sku-white（transparentImageUseImageType="1"）。无合格白底时先模型/JoyAgent补白底；只有第一主图已预览合格才可明确选择main-image（类型"0"、索引"1"）。失败预览不连续尝试第二第三主图。

```powershell
python -X utf8 scripts/pop_browser.py batch-cutout --profile-dir <owned-shop-browser> --expected-shop-name <shop> --expected-shop-id <shop-id> --mode sku-white --max-pages 1 --receipt-path <new-receipt.json>
```

UIcreateTask参数：taskType=1、srcId=37、businessIdList为本次准确SKU；contentMap.excitMaterialNotReplace="0"表示勾选“审核通过/审核中的素材图不替换”。此字段与字面直觉相反，必须以实测UIpayload为准。sku-white不能同时混入白底源配置。

- 实际接口：dsm.media.service.materialTaskApiService.createTask。页面自带h5st签名；不能裸fetch或更换工具重放。使用Playwright route.fetch透传页面真实请求，校验后route.fulfill。
- 非200业务code不接受；零createTask/零回执不说submitted；在请求前保存intent，结果未知先对账。
- 自动流程按当前槽位白底已通过、透明真正缺失选择准确SKU，不替换pending/approved，驳回走新图修复而不是混在缺项批次里。
- 前端无法精确选定目标SKU时明确block，不用全选其他SKU补偿。浏览器任务只控制该店自己的后台会话，不复制用户工作profile。
- 保存接受回执不代表审核通过；最终逐SKU回查status3=审核中、4=通过、5=驳回。平台队列不可控，有限等待后明确pending，不无限轮询。

## 驳回修复京麦优先（2026-10-31）

页面：素材管理→商品编码多值查询→勾选SPU→批量图片→智能设置。预览接口`imageAlgoGenerateService.getSkuGenerateMaterialPreview`逐SKU返回errorMsg（“智能抠图失败;”）。保存只提交“整组全选”的SPU：组内去勾个别SKU时平台不发createTask，因此保持整组勾选并依赖“不替换已通过/审核中”保护兄弟SKU；预览失败的SKU记为preview-failed，直接进入新算法。只点可见“智能设置”的保存按钮；隐藏“统一设置”保存会发空的imageRelations.batchBind，必须拦截。浏览器身份以店铺ID为准（页面店名可能是另一个展示名）。

旧实测表明营销拼图主图抠图易损坏；SKU白底抠图优先。不得将历史通过率当本店当前结果。
