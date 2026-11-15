# 原生规则 → 全 SKU 自动编译 → 来源基线

由 Agent 执行：product-schema --profile <merchant-profile> --product-id <actual-id>，随后 schema-edit-prepare --capture-id <id>。只读业务取数与本地准备，不提交写入；用户仍只描述目标、必要时扫码和批准明确写入范围。

schema-compile --capture-id <id> 可单独查看编译 capture、自动 bindings/saleSources 和原 capture 证明；schema-edit-baseline 的手工文件入口保留供已查明协议的高级宿主适配，不要求商家使用。

## 编译依据与不变项
- primitive 值使用原规则的 productDetailField；真实 SKU 身份与编码/价格/库存使用已核实 native 字段，ID/UUID 为同一真实 ID、位于前两项。空 SKU value/childrenComponents 规则展开为全部原 SKU；已有填值 SKU 保留原行顺序，并核实实际 ID。
- 复杂图片按原声明的记录集合 materialize，原图槽、顺序、颜色引用和未知业务值保留；原详情按明确 desc 声明处理，不造 HTML。普通/销售属性按原组和真实 attrId 选择，完整源 census 必须覆盖；颜色 mappingId 空时用原 attrValues，不造映射 ID。
- 未知值即使含 componentCode 也保持 opaque；只有明确的规则容器按 DTO 展开。value 与 properties 都不能静默删，缺原来源声明即拒绝；不拿其它相等值当来源，不把 boolean 当数字或版本 1。
- 编译值、bindings 和销售来源由同一确定性算法产生，字典键顺序不改结果。原规则元数据完整留在原 capture；正式 body 仅业务 DTO。

## 派生记录证明与恢复
原 capture 不覆盖。派生 capture 保存 rawSchema、原 capture ID/fingerprint、编译器源码 SHA 与源/结果/绑定哈希。读取时从原模板和原详情重新编译，并核对原 capture；重算文件指纹也不能洗入修改的声明/字段/类型。rawSchema 别名必须有完整 compiler 证明。

自动基线可重入，同一原 capture/编译结果沿用同一持久编辑意图；重复编译或新 validation nonce 不表示重新批准正式 POST。准备与缓存返回前仍查当前原详情、原规则、全部 SKU census 和店铺。漂移、原记录变化或派生冲突停止，不重提 unknown，也不清空日志绕过。

基线后使用 native-full-edit.md 的原图/明确详情修改、两阶段批准、600 秒/最终截止、已审官方 stdin、原申请单及完整字段回查。编译/本地完成不等于平台校验成功或线上生效。

## 真实限制
没有 field declaration 或已证明复合映射的组件拒绝，需 Agent 查明当前官方协议/真实合法数据，不要求商家编写 JSON。开发用与匿名官方字段声明一致的合成模板，不把它当全部线上类目兼容性验收；真实授权/API/线上状态语义和发行许可仍待完成。

health-infos 是健康分，不是已证明等同的京麦商品信息分；commodity-score 来源和信息分专属素材槽位绑定仍为独立任务，不以此整版编辑或图片空间保存代替。媒体模型来源继续等待负责人补充，编译器不调用任何模型。

存在 childrenComponents 与已填 value 时保留原 business children 及额外属性，再核对规则声明，不能用原型替换后偷偷丢字段。普通 SKU 属性使用 prop-sku/原 goodsAttrInfos 等实际声明，不能因为有属性记录就造销售维度；未覆盖原属性会拒绝。
