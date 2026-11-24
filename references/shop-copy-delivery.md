# 跨店照原样复制的运费、时效和退货

商家说“照原样复制”时，宿主先读源商品实际选中的物流配置，再用目标店自己的模板 ID 填写目标商品。核对模板时同时保留两店各自的 Profile、店铺 ID、商家 ID、模板 ID 和原始回执。已有目标商品应读取它当前的选中值，这样可以保留已绑定的等价模板。

## 优先取得官方证据

1. 读取源店商品编辑详情中的运费选择、商品级时效和每个 SKU 的时效。保留 `is7ToReturn` 和 `isPayFirst` 的原始值，包括 `0`。商品与 SKU 的时效分别记录，尺码、颜色与 SKU 对照沿用同一复制任务。
2. 目标店的类目 schema 提供候选 ID。`capture_freight` 在已核验的店铺 Profile 中查询能力卡 `GET.sp-seller.v0.shipping-templates._templateId`，按卡片的 GET 路径与入参读取已知运费模板。回执含请求引用、内容 SHA-256 和可用的输出字段定义。只传在该店实际看到的候选 ID。京东将此能力列在商家域第 179 项。[官方能力目录](https://mcp-open.jd.com/cli/skills/jdo-api-830/references/api-catalog.md)
3. 下拉项为空、只显示名称、回包字段没有单位或当前 Profile 缺少详情权限时，宿主使用该店已经登录的京麦商品编辑页、运费模板或时效模板页。展开实际使用的区域和计费条款，记下模板 ID、页面或本地证据引用。符合商家当前授权并确认目标店缺少等价模板时，可在可见页面按源规则创建，回读目标店返回的新 ID 和完整规则，再继续复制。
4. 读取失败时先交付商品的其余核对结果，说明缺的是哪家店、哪个模板、哪个区域或哪个 SKU 的时效。支付方式、运费承担方和七天无理由分别核对。运费选择空白时还应查商品实际继承的运费；判断包邮需要有明确的地区和适用条件。

## 宿主给对账工具的证据

两侧使用 `source`、`target`，每侧有 `shop` 和本侧观察到的模板记录。若官方详情的字段与 live 能力卡的输出定义完整对应，工具可直接归一计费规则。数字枚举须有卡片给出明确的值与含义。字段不全或含义未确认时，宿主结合原返回和官方可见页面补证。

以下是合成的目标店样例。`complete` 只在已查看该模板的全部规则、包括已展开的例外时填写。若规则来自 `freightReads`，同时填写该次返回的 `readSha256`。同店可选状态来自目标类目 schema、目标商品已经绑定的 ID，或目标编辑页实际可选的记录。

```json
{
  "shop": {"profile":"demo-target","shopId":"22","venderId":"32"},
  "freightTemplates": [{
    "id":"91","name":"标准配送","complete":true,"selectable":true,
    "receipt":"本地证据/目标店91号模板.json",
    "rules":{"chargeBy":"weight","unit":"kg","payer":"buyer","currency":"CNY",
      "zones":[{"regions":["江苏","安徽"],"firstQuantity":"1","firstFee":"8.50",
                "nextQuantity":"0.5","nextFee":"2.00"},
               {"regions":["样例限制地区"],"type":"excluded"}]}
  }],
  "promiseTemplates": [{
    "id":"92","complete":true,"selectable":true,"receipt":"本地证据/目标店92号时效.json",
    "rules":{"commitment":"付款后48小时内发货","cutoff":"15:00","holiday":"不顺延"}
  }]
}
```

`chargeBy` 使用 `item`、`weight` 或 `volume`，数量要附原单位。`payer` 使用 `buyer`、`seller` 或 `conditional`，条件运费还要保存 `conditions`。区域按实际配送、免邮或不配送条款记录，免邮行的 `type` 为 `free`。满额免邮、偏远地区、支付或承运条件等额外条款也放在 `rules` 中。不同单位先按官方定义换算至同单位，并保留原数值、单位和换算依据在各自的原回执中。

官方商品详情省略某个选择时，可用该商品编辑页补充，例如 `productSelections` 填写 `productId`、`receipt`、`WareTransport`、`WarePromise`、`WareSevenDayReturn`、`isPayFirst` 或按 SKU 编号索引的 `SkuPromise`。仅在页面确实显示继承时，才填空值。若商品运费明确为空，使用该店生效的 `defaultFreight` 记录完整规则。若商品和 SKU 都未设时效，使用 `defaultPromise` 核对实际的全店承诺。两类默认记录的结构均为 `complete`、`receipt` 和 `rules`。

准备草稿时，`targetValues` 的模板 ID 属于目标店，SKU 时效按原 SKU 编号交给已核对的规格映射。物流状态 `ready-to-apply` 表示草稿具备相应字段。提交后须回读目标店商品编辑详情，分别核对两层时效、运费规则、退货代码和支付方式。只有这些字段及 SKU 对应关系均有一致证据时，才会得到物流 `verified`。商品前台展示和审核阶段仍按相应回执交付。[京东官方组件说明](https://mcp-open.jd.com/cli/skills/jdo-product-update/references/components.md)

## 在目标店页面创建并核对规则表

没有等价模板时，由宿主从源页实际读取支付方式分组。把该行分组写进 `zones[].paymentMethod`；源页明确显示同一规则覆盖多种支付方式时，可用 `paymentMethods` 列出。运费由谁承担与“在线支付”“货到付款”属于不同字段。缺少支付方式时，先查源页，工具会保留已取得的地区、首续费和条件。

宿主使用本任务已保存的两店配送证据生成本地创建规则表。源模板编号来自原商品回执，生效的全店默认规则使用 `default`。

```text
python -B scripts/freight_page_draft.py --evidence <delivery-evidence.json> --source-template <源模板ID> --output <创建规则表.json>
```

在已核实身份、已获授权的目标店页面中，宿主按“支付方式 → 对应规则行 → 本行地区选择”定位。不同支付方式可包含相同地区且价格不同。地区树中文本或展开箭头会显示下级地区，应操作与本次地区对应的复选框，回读其勾选状态。地区使用可区分同名项的完整路径或官方编码。关掉地区选择后，再核对该行的已选地区摘要和首续数量、费用。页面局部未显示、行归属有歧义或费用不同的，重新定位该行；保留其他已证实的行。

由宿主记录可见结果，商家无需填写表格。回读文件传入目标店 `shop`、创建规则表的 `draftFingerprint`、证据引用 `receipt`、阶段 `editing` 及 `allRowsVisible`，再记录模板级 `globalFields` 和完整 `rows`。每行包括以下信息。

| 回读字段 | 证据 |
| --- | --- |
| `rowKey`、`paymentMethod`、`rowRef` | 对照创建规则表的行标识、实际支付分组、可区分该组内具体行的位置或本地截图引用 |
| `regionPicker` | 地区弹窗证据引用 `receipt`、是否已读全 `complete` 和实际 `controls`。每项记 `role`、`region`、`checked`；展开文本与半选父项不作为已勾选地区 |
| `rowRegions`、`fields` | 返回规则行后的已选地区清单，以及行内可见的首数量、首费、续数量、续费与其他条件 |

```text
python -B scripts/freight_page_draft.py --evidence <delivery-evidence.json> --source-template <源模板ID> --readback <页面回读.json> --output <核验回执.json>
```

`form-matches` 表示编辑表单与源规则一致。获得本次保存授权后，在目标店保存、重新打开该模板，按实际页面记录 `stage: reopened-detail`、`templateId` 和新的回读证据。`reopened-template-verified` 表示宿主提供的目标详情证据通过本地比对。接着用返回的 ID 读取官方模板，并在目标商品编辑页核对该模板可选和已绑定状态。此工具本身只读本地证据，不会发起浏览器操作或平台保存。
