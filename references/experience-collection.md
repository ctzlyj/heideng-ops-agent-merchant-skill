# 商品素材与逐SKU到手价采集

## 适用问题与事实

已有来源链接清单，只采标题/规格/主详情SKU图/视频/到手价，或给上新与比价准备资料。需要实际源链接、任务输出目录、来源平台、范围和商家/消费者已授权浏览器上下文。消费者商品页不要求商家 venderId 前置门禁，但不能绕平台登录/风控。

## 判断与建议路径

从商品来源表开始时，先创建任务输出目录，再运行 `python scripts/merchant.py run collection -- --root <输出目录> --input <来源表.xlsx>`。这一步读取表格并生成采集清单，返回的商品数可与来源表核对。商品页的价格和素材要在后续采集步骤取证。

- 默认复用原接口优先：每个商品自己的原生上下文读取SKU顺序和到手价证据；接口不具备实际条件时才采用原点击备用。宿主已有合法网页工具可补具体缺口，但不能套用另一个商品的上下文或Cookie。
- 价格与SKU同时锁定。包装/重量/赠品/会员条件、价类型和原页面选项要有对应；原生售卖组合没覆盖，就明确缺哪些SKU，不用虚构行补齐。
- 源价格不是到手价。只有本批用户明确接受原价备用，才让原 package_live 记录本批 opt-in；不能自动继承旧JD_*全局标记或固定日期授权。
- 建议按源平台响应控制批次/间隔。实际批上限/停止原因仍是原工具规则；调节支持的节奏是策略，不授权越过真实平台限制。遇登录/验证停止该部分，不因换工具绕挑战。
- 批驱动、checkpoint、打包和断点恢复沿用原实现；目标只采素材，不自动发布或写店铺。与 [比价](experience-comparison.md)/[上新](experience-listing.md) 组合时沿用真实源映射。

## 实际工具与证据

`run collection -- <prepare_batch原参数>`；登记 `collect_signed.mjs`、`click_collector.mjs`、`scripts/batch_driver/batch_driver.py` 和原 package_live/deliver_batch。必要环境/owned CDP 配置来自宿主实际任务，不猜端口、不清理工作标签。

完成看实际SKU和素材覆盖、价格类型/原生响应对应、包内映射/商品表、缺项和原验收结果；目录存在/ZIP生成不等于全部SKU价格已采到。对应源商品证据不得跨商品借用。恢复先读原checkpoint/响应，再补未完成项，不重启全批制造重复或混上下文。

## 来源与限制

jd-hot-link-collector 1.0.4 / 90ef8df；[价格SKU契约](../mature/collection/references/price-and-sku-contract.md)、[素材包](../mature/collection/references/package-contract.md)、[限速恢复](../mature/collection/references/rate-limit-and-recovery.md)、[浏览器配置](../mature/collection/references/browser-session-setup.md)。仅整理原已有路径；不能把消费者采集授权扩展成店铺发布许可。本轮没有真实采集/长批次/宿主登录实测。

给定店铺表时，使用 `run --entry scripts/shop_table.py collection -- --input <工作簿> --root <目录>`。批次按每个 SKU 记录价格来源。主图下载或 JPEG 校验失败时，包装器可尝试同一京东图片主机上的标准尺寸，按实记下原图、备用地址和是否成功。交付回读应保留素材替换与价格来源记录。
