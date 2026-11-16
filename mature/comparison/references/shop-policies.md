# 店铺配置与安全执行

## 范围与入口

此文档负责店铺配置与可选文件导出；默认本店采集、计划及确认后线上改价使用 [jingmai-api.md](jingmai-api.md) 的官方 CLI 路径。没有自动活动报名、自动获取全部活动或全品类规格识别能力。CLI 工具由 Agent 使用，不要求普通商家输入命令。只复用商家已安装、已授权的官方 `jdo-cli`；外部 CLI 路径与商家 `JDO_HOME` 由父启动器提供，不读取凭据文件或绕过登录。

`store_pricing.py` 接受非 default 的显式 `--profile`。每次命令只查询一次官方 `GET /rest/sp-seller/v0/venderinfo`，核对独立的 `shopBaseInfo.shopId`、`data.venderId`、店名、POP 类型，不将 venderId 当 shopId 后备值。账号权限或身份异常即停止，不自动重试、登录或切换浏览器。其他项目的店铺授权不自动扩大当前任务范围。

```powershell
python scripts/store_pricing.py identity --profile "<已授权Profile>"
python scripts/store_pricing.py show --profile "<Profile>" --shop-id "<真实shopId>"
```

身份由京麦账号证明，目标店铺由用户任务确定。禁止扫描所有 Profile 后自选店铺。店名变化也停止，不静默改绑；核对新旧身份后人工处理迁移。

## 持久配置

默认状态目录 `${HEIDENG_MERCHANT_HOME}/comparison/stores/jd-pop-<shopId>/`；`--state-dir` 只供测试或明确的私有部署。必须在安装目录外。多个 Profile 指向同一店时共享配置，不同店永不复用。配置只包含非敏感业务规则；Cookie、Token、密钥和账号凭据禁止写入。未知字段被拒绝。

新店首次可选择以下安全配置；不是系统自动替商家选择活动：

```json
{
  "activity_model": "none_v1",
  "strategy": {"kind": "compare_only", "direction": "all"},
  "limits": {}
}
```

`strategy.kind`：`compare_only` 不给目标价；`match` 与竞品同价；`fixed_gap` 配 `amount` 表示低固定金额；`percent_below` 配 `rate` 表示低百分比；`fixed_target` 配 `amount` 表示指定目标价。百分比接受小数或大于 1 的百分数，15% 请传 `0.15` 或 `15`，1% 必须传 `0.01`；不要传裸 `1`。负数、非有限数及百分比达到 100% 被拒绝。

`direction=all` 对所有 SKU 重新计算，包括当前已达目标价的 SKU，以保留历史“最高可精确命中京东价”规则。`down_only` 仅降不涨，已经更便宜或相同的 SKU 标记 KEEP，不进入上传表。`limits` 可指定 `min_final_price`、`max_change_amount`；越界停止整批，不自动压到边界，不宣称原策略成功。未配置成本数据时不输出毛利保证。

```powershell
python scripts/store_pricing.py configure --profile "<Profile>" --shop-id "<shopId>" --shop-name "<完整店名>" --config "<私有配置.json>"
```

首次调用只输出将写入的配置和 `confirm_token`，没有保存。用户确认显示的完整请求后，重新执行并附 `--confirm-token "<令牌>"`。配置修改或期间发生其他写入都会使原令牌失效。历史版本 `00000001.json` 等不可覆盖；保存使用同店写锁、原子替换与独立回读。异常锁不得直接清除，先核对保存的 PID 和进程，再经用户确认处理。

历史用户可以将 `--config` 换为 `--legacy`：明确迁移该店“旧直降国补模型、竞品减 0.10、全部 SKU 对齐”。只允许无配置的店铺执行一次；不需要用户重复说明已有策略，且不填历史活动比例。不能给陌生新店默认执行 legacy。恢复历史策略用 `rollback --revision N`，同样先预览再确认，生成新版本而不删除历史。

## 活动模型

- `none_v1`：明确无活动，两种比例都必须为 0。
- `direct_v1`：仅比例直降，国补比例必须为 0。
- `legacy_direct_subsidy_v1`：原模型原样保留。直降金额为 `round_half_up(京东价 × 直降比例, 2)`；国补金额为 `round_half_up(京东价 × (1 − 直降比例) × 国补比例, 2)`，最后相减。注意国补计算基数使用未舍入的比例表达式，不能悄悄改成扣掉已舍入直降金额后的余额。

每次改价单独确认活动起止时间、比例、适用 SKU；配置仅保存模型，不声称已报名或永远生效。当前价格证据、preflight 和本轮活动确认默认最多 15 分钟有效，未来时间也被拒绝。批次 SKU 必须与活动 `sku_ids` 完全相同；不同活动的 SKU 拆为独立可审核批次，不从全店推断全部适用。

不支持券、满减、补贴封顶、会员/新客限定、多件凑单等复杂情形。不能临时编公式或当作零折扣。只有条件一致的普通单件价才使用 `ordinary_single_item`。无活动与未知活动必须区分。

## 计划请求

输入在旧 `expected_competitor_sku_ids`、`competitor_skus`、`own_skus`、可选 `overrides` 结构之上，增加以下字段。文件导出路径的 own_skus 必须来自本轮选定店铺的文件或已核验采集；声明 shop_id 本身不证明 SKU 所有权。默认 API prepare 会重新查询官方归属、完整规格和京东价，显式指定范围时可省略 own_skus。

```json
{
  "shop_id": "<真实shopId>",
  "mode": "repricing",
  "captured_at": "<带时区的采集时间>",
  "preflight": {"status": "READY", "purpose": "price", "checked_at": "<本轮门禁时间>"},
  "price_context": "ordinary_single_item",
  "activity": {
    "model": "none_v1", "direct_rate": "0", "subsidy_rate": "0",
    "starts_at": "<实际生效时间>", "ends_at": "<实际失效时间>",
    "confirmed_at": "<本轮用户确认时间>", "sku_ids": ["<本批SKU>"]
  }
}
```

以上是补充字段示意，须与真实 catalog 合并，不能作为可执行的伪造证据。`preflight.purpose=price` 对应现有脚本；`repricing` 也是接受的同义值。`mode=comparison` 不需要 activity，也不创建上传表。竞品仍要独立完整枚举、逐条确认尺寸和价格。同尺寸多价格必须有显式图案 override；链接必须是与 SKU 对应的干净 `https://item.jd.com/<SKU>.html`，不保存签名参数。

本轮换策略可提供完整 `strategy_override`，不改变持久配置。计划绑定店铺、配置版本、全部输入和计算结果的哈希；保留每项舍入结果、目标价及策略核验，不再统一断言所有店都是 `final_difference=-0.10`。

```powershell
python scripts/store_pricing.py plan --profile "<Profile>" --shop-id "<shopId>" --input "<本轮输入.json>"
```

上述 store_pricing 命令是可选“只导表”入口，默认只输出计划 JSON。`mode=comparison` 可直接附 `--output-dir` 保存只读核验工作簿，绝不生成上传文件。商家明确确认导出 repricing 计划后，重新执行同一命令并附 `--confirm-token "<令牌>" --output-dir "<新的私有输出目录>"`。重新查询身份、重新加载配置、重新计算；请求变化、配置变更、证据过期等使确认失效。默认线上执行改用 jingmai_api.py，不把导出令牌当 API 计划令牌。

导出包含 plan.json、comparison.xlsx、receipt.json，有实际变动行时另生成 upload_rows.json 和基于内置模板的 price_upload.xlsx。KEEP 行留在核验表，不进上传表；没有变动就不生成空上传表。文件不覆盖已有目录，所有工作簿重新打开核对，回执包含文件哈希。出现导出异常，整目录按未交付处理，不单独使用残留上传表；重新生成新目录。最终仍应渲染工作簿人工检查布局。此文件导出器的 API 写入始终为 false，不代表独立 API 执行器没有写能力。

## 更新与回滚

商家移植不携带上游个人目录安装器、同步器或自动安装逻辑。父级分发按 provenance.json 的 files/sha256 检查原始字节；更新前必须保留已确认店铺配置，不能用源码更新覆盖状态。所有配置在 `${HEIDENG_MERCHANT_HOME}/comparison/stores` 下，`--state-dir` 只能指向同一商家命名空间。业务策略回滚继续使用原 configure/rollback 的版本机制，而不是用新配置状态机替代。

## 验收与停止

离线覆盖三模型、店铺隔离、同店多个认证 Profile、原策略逐分一致、临时策略不持久化、配置版本回滚、失效确认、身份/有效期/活动范围/价格限制和非破坏式更新。真实推广仍先选三种不同模型店铺各 1 个 SPU，先 1 条再 10 条；没有该店授权不扫描，不用离线样例伪称平台已验证。不支持的活动、分类匹配或缺失证据停止调价，保留比价证据用于人工确认。
