# 原生模板自动编译与来源基线计划

2026-11-15；接续代码 c3f9dfe / 验收记录 c4a284e，上一轮为实质进展。当前独立工作区实施，仍不做真实 OAuth、店铺写入、付费生成或正式公开发行。

## 设计裁决
商家只描述目标；Agent 不应被迫手填全 SKU DTO、bindings、sale-sources。采用从同店实时 capture 的原完整详情与原规则模板自动编译的路径，复用原整版两阶段写入/回查，不复制内部源码。其余可行方案为继续手填（不解决上手缺口）或搬入旧内部填充器（权限/依赖/来源不合格），不采用。

编译 primitive 字段直接使用原 productDetailField 声明；真实 SKU ID / outerId / priceInfo.jdPrice / stockNum 使用已核实 native 协议。处理纯规则 childrenComponents、空 SKU value、已填充 SKU、复杂图片/详情/销售属性和 opaque business 值。按实际 SKU/attrId 选择原记录，保留全量 source census、颜色 mappingId/fallback、未知 business blob；不依靠数组位置、相等值猜来源或默认值造商品事实。

编译后的 capture 保存完整原模板、原 capture 标识和编译证明。读取时从原模板/原详情重新计算编译结果，不能将调用方伪造的 field declaration 洗成可信原字段。原 capture 不覆盖；自动基线可重入、保持同一持久编辑意图，不借重复编译重放正式 POST。实时原详情/规则哈希与店铺身份变化仍阻断；正式提交只传业务 DTO，不传规则元数据。

未知协议且无可证明 source hint 的字段拒绝并指出具体组件，不删 unknown business 值。此为通用声明驱动器与已核实复合协议，不宣称所有线上类目模板已实测。后续实际商家/API/线上状态语义仍需授权验收。

## 任务与测试
1. 重新校验匿名官方文档与版本/SHA，仅读公开内容、不运行带认证的 info、不切 pre。核对当前商家 MIT 候选实际能力，区别健康分和商品信息分。
2. tests/test_template_compile.py 先 RED：带真实原 ID 的 1000 SKU 原纯规则模板自动 materialize；metadata 只留在 source；全部 leaf provenance 自动产生；图片/详情/销售属性/未知值保留；未声明/错字段/销售属性缺项拒绝。
3. template_compile.py 独立编译器，ProductSchemaService 编译 capture/读时重验，EditService 自动 baseline + CLI。测试可重复准备不新建正式意图；原字段/模板/店铺漂移及伪造 compiled 记录拒绝。
4. 必要的原全镜像绑定范围按实际源槽位验证，不用固定条数截全量 SKU；先以失败用例证明再调整。保持 HTML、真实上传回执、双阶段批准、600 秒/最后 HTTP、unknown 和全字段回查保护。
5. 更新项目 Skill/README/命令与限制；健康分不得冒称商品信息分。运行全 suite、打包/脱敏审核、安装后 raw-template 全 SKU 自动编辑和旧五组回归；私有推送后真正 GitHub clone 重建/安装回测；只提交脱敏汇总。

## 发现的真实缺口
官方 jdo-product-material 当前六接口是媒体空间，不提供信息分槽位绑定或视频上传；商家候选源码主要生成/填 Excel，不能冒充已自动上传绑定。其商品信息分数据来自京麦 commodity-score；现有 health-infos 是健康分接口，语义尚未证明等同信息分。正确区分，不用健康分或主图整版编辑作为信息分维护完整完成的替代。继续保留信息分专属来源/槽位绑定、正式发行权利、真实商家链路的目标范围。

## 实施与一次有界评审
自动编译/派生 capture/可重入基线与两个 CLI 入口已实现。初始 helper 把规则误交给只接受 DTO 的函数，已分离规则验证；TDD 又确认并修复显式容器投影、value/properties 保留、rawSchema 别名必须有编译证明、严格 JSON 类型（boolean ≠ 数字/版本）及字典顺序稳定。

一次只读独立评审的三项具体问题均以 RED 复现后处理：已填值子属性被 childrenComponents 原型替换、原属性记录在缺组件时漏覆盖、子 value 的派生声明丢失。修复以已有 business children 为主并与原定义核对，属性源全 census 必须被原规则组覆盖，完整保留子 value 和声明；追加多图原型逐位置核对与已填值销售属性保留。

Ruling：官方 01 指南中 goodsAttrInfos 对应普通 SKU 属性（prop-sku），不能单凭有属性数组就判为销售维度。缺少任何映射的原属性拒绝；普通属性按真实 attrId 和共享属性定义保留，不造 VenderCategoryValue。开发 sales 数据改用合成 saleAttrs 字段，实际字段始终取原模板声明，不将合成路径称为真实商家 SDK 字段实测。

现有整版变更闸门实际已允许 10000 条明确指针，而非草案旧 1000 条；无需猜测并改动上限，本次不截原全 SKU。首个安装 smoke 因测试误用不存在的 product-schema-show 停在写入前；经真实 parser 核对改用 schema-capture-status，原柄终态后重跑通过，不是生产请求重放。最终评审修复后的包需重新构建并完整回测，早期 4a857... 包的结果不冒充终验。
