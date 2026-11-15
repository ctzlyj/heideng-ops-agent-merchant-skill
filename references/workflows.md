# 商家业务闭环

## 经营/广告诊断
先inspect-source，Agent根据用户报表列名建立mapping到revenue/orders/adSpend/adRevenue/stock/uv/pv，确认期间和口径。diagnose只分析上传行，不声称全店完整；缺项partial/unavailable，不补0，不以广告ROAS当利润。用宿主推理解释问题和建议，真实广告投放另授权；没有本店商智/京准通登录可继续分析用户报表，不能转黄金眼/EasyBI/ERP。

## 信息分/主图详情
核对全部SPU/SKU和官方问题因子。报表 material-audit 保留全部SKU；原生单商品使用 sku-material-audit，核对完整原商品/SKU分页与素材，按50个SKU拆批。sku-material-plan 仅填不存在的槽位，原上传回执和宿主已复核文字作为来源；商家批准完整计划一次后，sku-material-execute 逐块执行与全范围回读。待审/驳回/已存在素材只报告，不自动覆盖；unknown保留原任务并停止后续写入。优先复用用户已审核素材，宿主可以策划/识图复核；新图生成待模型来源。上传/原子更新前读官方material/update协议，核对实际zoneId/类目/商品/照片hash，独立计划与批准，再核对审核和线上状态。不把素材缺口报告当维护完成。

## 上新/复刻/实拍
真实商品来源与权利核对→完整SKU/规格/价格库存→本地主图/详情素材→prepare-listing。未上架包不造京东SKU或商品URL。当前manifest是merchantPackageSchemaVersion=1；旧内部mover包不是可直接同名覆盖的已验收包。正式发布还需官方类目/schema/必填属性校验，再以官方product-applies提交与审核/线上两段回查。缺必填信息问具体缺项，不借员工SDK补。

## 同规格比价/改价
同一原生商品上下文逐SKU取得真实到手价，保存选中款/规格/价格类型和证据。compare只匹配相同结构化规格，不混净重/包装数量/赠品/会员专享价；缺证据排除并说明。

正式改价要取得真实productId/applyId/categoryDetail和skuId，不按名称猜接口。当前官方更新用PATCH product-applies与SkuJdprice组件，需审阅最新update协议；不得用旧PUT products测试fixture作为实际API。用户看过方案并批准后执行，待审值和线上值分别核对。

## 视频
图片/视频生成来源暂待确认，任务不读取员工Key或默认收费平台。既有用户视频和封面可attach-video；技术、视觉、试听与文件hash一致才bindable，绑定另授权。官方material当前提供视频列表查询，不提供视频上传；不能把查询出口当上传成功。可由Agent在商家已授权视频上传页面执行并回查真实回执，尚未实测的链路不声称已验收。

## 结果证据
准备、提交、平台审核、线上生效和经营改善分开标记。unknown只能读回执/远端，不能重提/换工具重提/删状态。task-readback证明目标状态，不证明未知提交的作者归属。

## 两种来源与生成解锁

视频工作流代码来源固定指定GitHub仓库，不等于生成模型服务来源已选定。源码发现/版本审核不授予生成、费用或店铺写入权限。实际生成需要负责人确认外部服务与当前模型/参数/价格/账户能力、对应协议适配通过测试、商家安全设置自有Key、并批准该任务的镜头/次数/预算；缺任一项仍awaiting-provider，不用员工Key补齐。

unknown的目标状态匹配只记录事实，不解除原请求未知：任务继续unknown直到原请求能被关联的官方终态核对完成。
