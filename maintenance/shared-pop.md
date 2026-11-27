# 两个入口共用 POP 修复

| 一线问题 | 修改与补回归的位置 | 商家来源组 |
| --- | --- | --- |
| 续登时核验原 Profile 绑定的店铺身份 | jingmai-cli-linker | connection |
| 经营诊断的检查覆盖、部分结果和报告复检 | jd-store-diagnosis-skill | diagnosis |
| 搬家两端的 SKU 配对、源材料、目标链接、短标题 | jingmai-hot-product-mover-skill | shop-copy |
| 实拍上新的已接受样张与原图位复用 | jingmai-hot-product-mover-skill | listing-samples |
| 采集断点、店铺表及价格降级回执 | jd-hot-link-collector | collection |
| 同规格比价、价格计划、明确拒绝和回查 | jd-competitor-price-adjustment-skill | pricing |
| 已审核视频交接和验证 | jd-main-video-batch-skill | video |
| 可编辑分层打标模板及图层核验 | generate-psd-label-template | psd |
| 本地图片制作无声候选 | jd-main-video-batch-skill | video |
| 搬家批次冻结、暂停、恢复、状态和交付 | jingmai-hot-product-mover-skill | shop-copy-batch |
| 一个类目的热卖 SKU 聚合草稿 | jingmai-hot-product-mover-skill | top-sku |
| 限定商品的素材缺口、SKU 读数与覆盖 | jd-material-pop-skill | materials |
| 图组、已认可样张、上传恢复、按图位回读 | jingmai-batch-image-refresh-skill | refresh |

1. 在业务仓加入可公开的合成回归，先走真实业务入口记录失败，修复后重跑。在修复 PR 写出源提交、回执字段和复现命令。
2. 采销入口登记验证过的业务仓提交。商家在本仓执行下列命令，从本地业务仓的 Git 对象复制来源组内的文件和共用测试。一组以外的来源继续使用原提交。

   ```sh
   python scripts/sync_shared_pop.py --group <来源组> --source <业务仓路径> --commit <40位提交>
   python scripts/sync_shared_pop.py
   ```

3. 新增共用文件时，在 `maintenance/shared-pop.json` 给对应组补源路径、目标路径；作为商家命令入口的文件也列入 `entrypoints`。同步器更新文件 SHA256、成熟组件的逐文件来源和商家安装清单。维护者审查差异后，从两个宿主的正常入口跑同一份合成样例。商家离线回归用 `python -B tests/run_mature_offline.py --source-only` 和 `python -B tests/run_usability_offline.py --source-only`；安装验收用 `python -B tests/run_merchant_journey.py`。
4. 两边可以分别合并和发布，PR 指向同一业务提交和同一份测试。商家从公开 GitHub 提交安装，只需商家自己的店铺授权。任务版本回执的 `sharedPopCommits` 列出该快照携带的各组提交，安装目录的 `maintenance/shared-pop.json` 记录每个文件的来源和 SHA256。公司身份、模型网关、商家密钥和各自的费用回执由宿主适配层持有。

其他成熟组件的整版升级继续走 `scripts/upstream_updates.py`。批量升级遇到逐文件固定的共用实现时，保留该文件的来源，维护者用对应来源组推进。
