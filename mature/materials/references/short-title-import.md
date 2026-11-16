# 短标题自动导入（2026-10-28）

`auto-maintain --profile-dir <owned-shop-browser>` 自动串接导出、导入和平台回读。不得只交表让用户上传。单独恢复导入：

```powershell
python -X utf8 scripts/pop_browser.py import-short-titles --profile-dir <owned-shop-browser> --expected-shop-name <shop> --expected-shop-id <shop-id> --workbook <validated.xlsx> --receipt-path <receipt.json>
```

1. 用当前店铺CLI和该浏览器身份核对店名/id。
2. 重新校验官方模板、准确文本SKU、长度16–30和重复；不要更改已合格SKU。单任务5000行、xls/xlsx、5MB。
3. 商品列表“更多批量工具”→“批量设置短标题”，**仅抽屉内部**input[type=file]，避免整页其他文件控件。
4. 上传文件名显示后，保存intent并点击“确定导入”；必须取得createImportJob成功业务响应和新增真实任务ID。任务类型jobId不是任务ID。
5. 刷新原任务到已完成，记录成功/失败条数；未知时只查询不再点导入。任务创建/成功行仍不证明正式标题审核通过。
6. 回查目标SKU的health-infos hasShortTitle，清零才标verified；重算有延迟，保持awaiting-review而不是重新导整表。

加权汉字2、其他1；使用汉字/英文/数字，建议≤28，避迷信/促销词。平台确认失败明细后只补这些SKU，不推断剩余行已接受。导出文件≤10000行可供统一留档，导入超过5000由内部任务切分，不让用户拆表。

结果字段区分ready-for-import、import-pending、import-completed-awaiting-review、verified、unknown与具体blocked。仅用户明确选择人工兜底时交可上传表；已自动导入的最终表标“留档”，避免重复提交。
