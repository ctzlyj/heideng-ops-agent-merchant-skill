# 整店主图/详情图刷新：成熟复用

来源 `ctzlyj/jingmai-batch-image-refresh-skill` 1.4.5 / `8a2f3df185562b1f2f27859a90080d19b2f259cf`。
从 Git blob 选择 20 个必要脚本+requirements，另附确认分发范围；未复制 bundled jdo-cli 二进制、jx_joyer 公司 SDK、个人安装或运行目录。

## 真正执行链
`image-refresh/new_job -> build_plan -> download_sources -> generate -> upload -> patch / patch_detail -> verify -> report`，独立脚本已注册且实际派发可达。
原 job.json 的店铺/Profile/商品范围、主图颜色组/槽位、详情 src-only 逐字节约束、身份回读、上传/写回回执、独立终验和 Excel 输出均来自成熟源码，不再另建图片优化器。
`_common` 只将资源寻址改为已校验的包内成熟 mover；CLI/large-body bridge 使用该 mover 的原代码，安装授权仍由独立安装器和成熟连接器承担。

## 外部付费必要适配
生图客户端收敛为 LTS4AI gpt-image-2.5，经原 sufy 客户端，不复制公司请求协议或读用户注册表 Key。
原 first planned image 的 preflight 结果仍用于该图片，不额外生成样图。失败/结果不明通过原 generation ledger 保存原尝试；不再走公司模型 fallback，不自动等待额度后重提，不自动重启付费/写入步骤。
这不是新业务状态机：复用原任务台账和原 status 字段；外部 provider 未提供可靠任务对账路径时宁可明确 unresolved，不制造成功证据。

## 验证边界
已跑实际纯规划/新任务 JSON、源 HTML src-only 替换、包内成熟 mover 寻址、单次原 sufy adapter 调用、未知首次图片不重提及编排不自动重启测试。真实商家取数、上传、写回、LTS4AI 费用/生成未执行。
详情页仍保留原一次单品 pilot 和 `detailWrite + --write --confirm DETAIL_PATCH`，未实写不称完成。
图片 slot/SKU 更新继续由原 mover/POP 路线承接，本 source 的整店范围是主图+详情图，不冒充所有图片业务。
