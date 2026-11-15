# 原范围短标题健康来源设计（C3 必须项，不是完成替代）

目标保持完整：商家安装一个仓库，Agent 完成合法 POP 流程。当前正式短标题审核与门户没有已核对的原生契约，不能用 bossAuditStatus（商品采销审核）或 health 标志代替。本阶段先补已有官方契约的完整 native health 列表/详情来源，仍不放开 C3 terminal/失败重投/更新门禁。

## 已核对来源

以官方公开 version-policy 的发布路径与 SHA256 校验18份 product price/status/update/material/publish 文档。此次获取 policy SHA256 acd1914caceebb8c00e24d98ee587fbaddefe3ab75f74eabd2fe782398e1c424；字段文档 SHA256 3d049c742490d73665ac1ae57b182fc6add0b574319c62edd764b3594d43688f。health 列表已有代码，详情路径 /rest/sp-product/v0/health-infos/{healthInfoId}，参数healthInfoId对应skuId；数据skuId/productId/healthScoreId/healthScore/improvementList。仅有正式文档证明的字段加入实现，不猜短标题审核端点。来源条目只保存公开路径/hash与判断，不复制原始第三方资料进入分发包。

## 我的实现选择

沿用现有Python标准库、ProductService与持久worker原owned guard，不新增浏览器、账户中台、公司服务或生成模型。新增小型健康来源模块，所有原兄弟SKU包括离线/缺行保留；每行查详情并校验SKU、product与health ID，不拿某SKU的健康事实归给别人。仅同一商家身份、原scope、前后详情/全量health列表与详情一致时，声明native健康来源已核验。sourceData（例如图片URL）只参与内存中的原数据hash，不保存/回传签名URL、原响应或凭据，也不访问sourceData URLs。

C3 v2记录新增nativeHealthEvidence、nativeHealthSourcesVerified和targetHealthRequirementsSatisfied；现有列表healthScore/healthTitleIssue语义不被悄悄替换。v1原件仍严格验证/历史保留，v2字段有语义重建而不只信bool/hash。healthVerified/formalAuditVerified/portalVerified/imported/retryAuthorized继续不能因这部分健康证据为true。缺源/错SKU/字段错型/冲突/前后不稳定保留原行并报告unknown；owned guard/当前店身份丢失则拒绝新完整观察。

## 硬约束

业务只用合成shop/HTTP/browser/审批/template，不运行真实OAuth、jdo info、登录浏览器、商家API/写入、模型、消息或公开发布。允许本轮公开官方文档下载；内部仓库、全局安装Skill及上游只读。生产入口不开放mock/runtime/身份绕过；新观察不删除旧prefix，不自动重投。超过原64MiB effect记录限制拒绝，不截断。完整terminal、正式审核/门户与确认失败子计划仍为后续必须实现的目标，不缩成健康审计交付。
