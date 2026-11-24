# 短标题自动导入（2026-10-28）

`auto-maintain --profile-dir <owned-shop-browser>` 自动串接导出、导入和平台回读。不得只交表让用户上传。单独恢复导入：

```powershell
python -X utf8 scripts/pop_browser.py import-short-titles --profile-dir <owned-shop-browser> --expected-shop-name <shop> --expected-shop-id <shop-id> --workbook <validated.xlsx> --receipt-path <receipt.json>
```

1. 用当前店铺CLI和该浏览器身份核对店名/id。
2. 使用官方 XLSX 模板，核对文本格式的 SKU、短标题长度（16–30）和重复行。只修改本次已交办的 SKU。
3. 商品列表“更多批量工具”→“批量设置短标题”，**仅抽屉内部**input[type=file]，避免整页其他文件控件。
4. 上传文件前记录该批的原文件指纹和店铺。上传后记录平台返回的文件标识，再点击“确定导入”。以创建任务的业务响应及真实任务 ID 继续回读。
5. 刷新原任务到已完成，记录成功/失败条数；未知时只查询不再点导入。任务创建/成功行仍不证明正式标题审核通过。
6. 回查目标SKU的health-infos hasShortTitle，清零才标verified；重算有延迟，保持awaiting-review而不是重新导整表。

加权汉字2、其他1；使用汉字/英文/数字，建议≤28，避迷信/促销词。每份可留档的导出表最多 10,000 行。导入时检查每个实际提交文件的两个上限：5,000 行和 5 MiB（5,242,880 字节）。合格的小文件可沿用，超限时把准确的 SKU 文本和标题写入官方模板，再按实际字节数决定是否继续拆小；原表留档。平台明确退回的行改好后也按这两个上限分批。某批仍在处理或回执不明时，保留原任务查结果。

回执中的 ready-for-import 表示可直接导入，ready-for-batching 表示需自动分批。平台受理后按原任务区分 import-pending、import-completed-awaiting-review、verified 和 unknown。已自动导入的原始工作簿标为留档，结果未知的批次先查原回执。
