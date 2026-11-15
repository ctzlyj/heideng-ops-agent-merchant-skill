# 原生全 SKU 新品校验与提交

沿用已批准的自主设计实施；同一私有分支，不做真实授权/商品写入/付费生成。上一轮有实质代码与GitHub回测。本轮不把校验计划或草案定义为目标完成。

## 新官方证据与决策
已按当前公开policy真实取得01-component-guide/02-category-attributes/03-sale-attributes/07-example-pop-unstructured。此前本地缓存未取得03不代表官方没有。指南明确：编辑SKU须SkuId、SkuUUid填真实skuId；新增SKU用唯一UUID；SkuVendorSku对应详情outerId；编辑色图mappingId从原详情取（空时用attrValues）。这修正了旧资料缺口，但仍需真实schema及回包佐证，不能仅凭名称推断。

新品不需把UUID映射成已有SKU ID。先完成这个完整请求闭环：已授权类目/三级品牌/销售属性/模板 → host按实时规则填写完整schema → 全SKU与照片来源预检 → 高风险validation精确批准/执行 → 原校验成功回执绑定、fresh源核对 → 全版POST独立批准/执行 → 原applyId/productId回执，不编造链接或线上图片效果。

## 文件与任务
1. heideng_merchant/publish_support.py：PublishSupport.context(profile,category_id,brand_id)，实际GET vender-categories（sceneType=3、categoryIdList真数组）、向上定位三级类目、vender-brands queryType=2/authStatus=2/pageSize<=20，必要的sale-attr-templates路径占位符、product-schemas新建时不传productId。完整模板/枚举不裁剪；权限不足不切pre/员工Profile。
2. heideng_merchant/publication_contract.py：原生flat新发品body、全部SkuUUid唯一且无既有SkuId，manifest全部merchantCode→SkuVendorSku、价格/库存和全部规格→VenderCategoryValue alias校验；全部imgUrl和商详src必须来自同Profile原已知上传回执/原照片SHA，未知/改动拒绝。根据实际template约束组件，不静态限制类目或销售属性ID；caller提供的spec_map必须覆盖完整规格，不能只过第一SKU。商详HTML限已审图片/文本，不允脚本/内部地址。模板必填和未知业务规则最终由native validation判定，不假称本地检查覆盖平台所有规则。
3. heideng_merchant/publishing.py与operations.py：validation是POST需明确批准，但只校验不会发布。处理官方文档明确success:true且data为空/无wareKeeperDetectResultList违规的回执；非空违规为已知失败，陌生report为unproven，不能提交。超时仍unknown且不重放。全版POST共享任务边界强制绑定已成功、原始回执SHA、同店、同body、TTL内的校验任务和manifest/schema/素材/授权实时证据，task-plan不能绕过。提交仅承认原applyId/productId，不把受理说成线上。已有整版编辑因完整旧值/映射/图片回查尚未实现继续拒绝，而非冒称已支持。
4. workflows.py/CLI/registry/references：实拍包保留完整sourceProduct；publish-context/publish-validation-plan/publish-validation-status/publish-plan/publish-status。同一次明确用户许可已覆盖相同schema的校验和条件提交时Agent可分别绑定两个实际任务fingerprint，不重复问同一范围；内容/源/执行版本变化需重新批准。

## 测试与验收
先写失败测试再实现；validations flat body、empty成功、违规/陌生/unknown阻断、错店/receipt改动/TTL/最后SKU遗漏或改价/规格缺失/照片变化拦截，POST不能绕过校验。保留完整源商品输入、结构化/非结构化mapID一致性及CDN商详来源。一次有界独立review，再clean套件/包审核/fresh安装/file-fake跨进程闭环、私有push后真正GitHubclone回测。真实商家链路及全线上图片/属性效果不由mock验收证明，整体goal继续active。


## 有界评审后的实施记录
一次独立评审指出四项 P1，均以失败测试实际复现：陌生外层/深层违规报告被误判通过；HTML 注释解析差异绕过 no-script gate（不等于已证线上 XSS）；复制目录重复创建/旧批准未失效；590 秒校验在慢传输前检后超过 600 秒仍可 POST。另复现小发布仍走 binary 和签名耗时后 HTTP 入口未拦截。

Ruling：新品发布与校验强制已审核官方 stdin，而非维持小载荷 binary——公开官方源 ABI 可在真实请求入口核对时限；二进制内部刷新/签名耗时不可在现有证据下保证。保留其它小 GET/操作的 binary 路径。

实现：完整 envelope 判据、根层执行元数据匹配；批准前安全 HTML 重构、共享边界拒绝非规范原文；manifest 持久创建意图与 nonce 分离、同物理店铺跨路径去重；最后前检再次核对校验，较早 deadline 传入官方 worker 并在签名后 HTTP 入口检查。没有扩建 SaaS 或跨机器日志协议。

初始包/初始 241 项通过仅为修复前基线，不能作为上述修复的终验；以随后完整套件、重建包、fresh 安装及真实 GitHub clone 的新证据为准。评审已关闭，本轮不重复派评审。

补充根因验证：官方 urlopen_with_ssl 有 TLS 错误 fallback；仅守在 helper 入口不足以覆盖第二次底层 launch。已以失败测试复现并在隔离 worker 内临时守住每次 native urlopen，结束时恢复，拒绝第二次业务 HTTP 尝试；GET 原重试策略不变。
