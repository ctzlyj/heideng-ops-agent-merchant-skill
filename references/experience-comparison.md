# 同规格比价与确认后的改价

## 适用问题与事实

本店商品与已知竞品同款/同规格比较、TOP候选筛选、定价方案、按已批准方案改价。需要正确店铺、商品SKU、规格组合、真实到手价/促销条件、成本或政策（确需时）、竞品来源与证据窗口。

只匹配同品同规格：规格重量/数量/包装与赠品/会员条件不能混；缺销量/店铺条件写“未展示/数据不足”，不要补0。

## 判断与建议路径

- 有已知竞品链接/用户表，就先走原证据解析与同规格比较，不强制额外图片搜索。只有确需图搜且已有合法可用工具才补发现；某独立图搜 provider 未配置是该路径缺项，不是禁止全部比价。
- 原采集证据、实际SKU到手价、排名与政策由原 same_product_market/jd_price_adjustment/jingmai_api 计算和读取。复杂活动当前工具未支持时，查官方当前规则或采用可验证来源/方法；不能猜公式、把标价当到手价或换接口试写。
- 用户已明确本次直接减免/国补费率、目标和范围时直接沿用。上游“每次问费率”说明不能变成黑灯重复确认；仅缺事实、条件改变或含义不清时问具体缺项。
- 准备方案与真实写入分开；已批准同一范围的改价方案进入原 execute，不增加第二套 approval。参数必须是实际 productId/applyId/SKU及当期契约；不得凭名称猜身份。

## 工具与完成证据

- `run comparison -- <same_product_market原参数>`。
- 登记 `scripts/jd_price_adjustment.py` 的原 plan 等入口，及 `run price-update -- collect|prepare|execute|status ...`。
- 方案交付带匹配/排除理由、价类型和证据、待执行范围；真实改价后分别记录受理、申请/审核和线上价格。目标当前价格相同不能独自证明某未知提交归属。
- 原结果未知，保留请求和读回；换工具可以核对，不可换工具重提。

## 来源与边界

jd-competitor-price-adjustment-skill 1.0.0 / 43bdf67；[原工作法](../mature/comparison/references/workflow.md)、[店铺政策](../mature/comparison/references/shop-policies.md)、[官方改价接口适配](../mature/comparison/references/jingmai-api.md)。源文历史平台与固定样本只作经验来源；公司浏览器/服务不是商家fallback。未获实际调价范围批准时只交分析，不写店铺。
