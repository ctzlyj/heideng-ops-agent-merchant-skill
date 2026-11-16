# 京麦官方接口执行

这是默认的本店取数及确认后改价路径，命令由 Agent 执行。商家用自然语言指定店铺、范围和业务意图，不需要准备本店价格 Excel 或记住命令。稳定店铺策略继续由 `store_pricing.py` 管理，读取 [shop-policies.md](shop-policies.md)，不可重置已有策略。

## 能力映射

只调用商家自行安装且已授权的官方 `jdo-cli`；由父启动器设置 `JDO_CLI_PATH` 和商家命名空间内的 `JDO_HOME`。核查官方业务 Skill 与精确接口 `info`，不能猜接口；不通过员工工具别名、个人配置根目录或自动安装获取能力。

| 环节 | 官方接口 | 边界 |
| --- | --- | --- |
| 当前店铺身份 | GET `/rest/sp-seller/v0/venderinfo` | 真实 shopId、venderId、完整店名交叉核验 |
| 本店商品分页 | GET `/rest/sp-product/v0/products` | 全店扫描须显式指定范围；前后清单核对 |
| 本店 SKU 归属 | GET `/rest/sp-product/v0/skus` | 先查归属再取完整商品详情，不用列表价格代替详情 |
| 本店详情及实时价 | GET `/rest/sp-product/v0/products/{productId}` | 完整 skuList、规格、款式、京东价和状态 |
| 价格诊断 | GET `/rest/sp-product/v0/price-stars` | handPrice、价格星级；空数据保持未知 |
| 价格申请 | PATCH `/rest/sp-product/v0/product-applies/{applyId}` | 仅 `SkuJdprice` 组件；不修改其他组件 |
| 申请单回查 | GET `/rest/sp-product/v0/product-apply/{applyId}` | 注意 GET 单数、PATCH 复数；再查线上详情 |

官方活动 `marketingactivities` 上报接口不是完整报名台账或自动报名接口。全站竞品识图、销量排序、完整活动与券叠加尚无已验证对应能力；继续复用已授权后台浏览器采集和本轮活动确认，不拿本店接口查别店后台，不以搜索展示价替代到手价。普通商家读权限不代表写权限。

## 只读取数

实测（2026-09-29，珍宝栖屋品牌甄选店 789 SKU 全量回读验证）：商品导入 Excel 的价格导入路径会把两位小数价四舍五入成整数生效；官方价格专用 PATCH 提交两位小数字符串（如 `156.80`）可原样生效，申请单与线上详情均按小数回读。需要保留小数价时不要走导入表，使用本接口并逐条回读。

```powershell
python scripts/jingmai_api.py collect --profile "<授权Profile>" --shop-id "<shopId>" --sku-ids "<SKU1>,<SKU2>" --output "<私有目录>/catalog.json"
```

`--sku-ids`、`--product-ids`、`--all-products` 三选一；最后一个只用于明确要求的全店读取，不直接生成全店改价计划。Profile 不得是隐式 `default`。未知/缺失/重复 SKU、分页总数变化、短页、前后全店清单不一致均停止。价格星级空数据不会变成零价，也不证明没有活动。其他可用数据保留，权限失效或限流则停止。

纯比价先用 `collect` 获取本店官方数据，沿用独立竞品核验；没有可靠本店到手价时标记未知，不把京东价冒充到手价，不为了补价格自动进入改价流程。数值尺寸/款式不能从官方规格可靠确定时，转人工核验；这不是已验证的全品类匹配器。

## 生成并预检计划

准备 [shop-policies.md](shop-policies.md#计划请求) 的输入 JSON，`mode=repricing`，补齐本轮完整竞品 `expected_competitor_sku_ids`、`competitor_skus` 和必要的显式 `overrides`。竞品采集需真实 READY discovery/price 门禁及带时区的采集时间，不能手写 READY 冒充检查结果。

```powershell
python scripts/jingmai_api.py prepare --profile "<Profile>" --shop-id "<shopId>" --input "<私有目录>/input.json" --sku-ids "<已确认SKU范围>" --output "<私有目录>/plan.json"
python scripts/jingmai_api.py execute --profile "<Profile>" --shop-id "<shopId>" --plan "<私有目录>/plan.json" --dry-run
```

- `prepare` 接受显式 SKU 或商品范围；不传时使用输入 `own_skus` 的 SKU 集合。显式范围下可以省略 `own_skus`，不需要本店工作簿。
- 重新从官方详情取得本店 SKU、规格、款式和京东价，不信任文件的旧价格。已有文件尺寸与官方尺寸矛盾时停止；下架或停用 SKU 转人工核验。
- 按店铺保存的活动模型确认本轮实际比例、有效期、适用 SKU；不重复问长期策略。确认范围必须与本轮全部 SKU 相同。多个活动拆批，不把未知当无活动。
- 本店用于计算的当前到手价为实时京东价加本轮确认模型的计算值，明确标记 `LIVE_JD_PRICE_WITH_CONFIRMED_ACTIVITY_MODEL`，不是结算页实测。旧模型复用逐项分币舍入，不改成最终一次舍入。
- 计划包含店铺、策略版本、原始门禁、标准化输入、计算结果、完整商品价格基线、非价格字段指纹、每条确切 PATCH 请求体及 `confirm_token`。实际京东价不变的行不提交；保存的 `direction=all` 语义不变。
- `--dry-run` 再查店铺、当前策略、证据时效、线上详情和申请单基线，不创建执行状态、不 PATCH。已执行过的计划先走 `status`，不要用原始基线 dry-run 代替恢复核查。

向商家展示店名、SKU 数、改前/改后京东价、模型到手价、目标策略、涨跌及风险，获得针对该计划的明确确认。软件升级、只比价、已报名声明或旧批次确认都不是本批写权限。Agent 将批准的计划令牌传入执行器，不能把自动拿到令牌当作用户确认。

## 确认执行和回读

```powershell
python scripts/jingmai_api.py execute --profile "<Profile>" --shop-id "<shopId>" --plan "<私有目录>/plan.json" --confirm-token "<商家已确认计划的令牌>" --output "<私有目录>/execution.json"
python scripts/jingmai_api.py status --profile "<Profile>" --shop-id "<shopId>" --plan "<私有目录>/plan.json" --output "<私有目录>/status.json"
```

执行器先 1 SKU，再最多 10 SKU，后续每组最多 50 SKU，按商品分请求。每次发出前核验身份、当前策略、完整价格及非价格字段、申请单，再核查证据时效；当前证据默认 15 分钟有效。每个请求完成申请单和线上回查才能继续。范围和请求体变化必须重新计划/确认，过期不继续派发。

PATCH 只使用官方 POP 平铺请求：`applyId`、`opType=3`、`scene=pop`、`productInfo.productId/categoryDetail`、`productApplyDTO.id`、`patchOperationList`；没有 `request` 包装。每个操作的 path 为 `skus[skuId==<id>]`，value 为字符串 JSON，仅包含 `componentCode=SkuJdprice` 与两位小数价格。已验证 POP 合约中 applyId 等于 productId，不外推到其他业务类型。禁止全商品重传、库存/图片/标题修改和活动操作。

默认状态在安装外 `${HEIDENG_MERCHANT_HOME}/comparison/api-runs/jd-pop-<shopId>/<plan_hash>/state.json`，同目录先归档完整确认的 `plan.json`，归档不同则阻断。可用 `--runs-dir` 指定商家命名空间内唯一共享的私有审计根目录；同一店铺的所有运行必须复用它，不通过换目录绕过锁。脚本在 PATCH 前持久化 `SUBMITTING`，本地 Windows 共享冲突仅重试原子文件替换，不重试远端写入。原始凭据、CLI stderr 和签名 URL 不写入日志。

| 状态 | 含义与处理 |
| --- | --- |
| `READY_FOR_CONFIRMATION` | 只读预检通过，仍需商家确认 |
| `NOT_SUBMITTED` | status 查到尚未提交，不自动写 |
| `PENDING_ONLINE` | 申请价格匹配，线上尚未全部传播；后续只读 status |
| `WRITE_OUTCOME_UNKNOWN` | 超时/拒绝或回执不明；先只读核验，禁止盲重发 |
| `UNEXPECTED_APPLICATION_ID` | 回执标识异常，暂停并核查 |
| `READY_TO_CONTINUE` | 已尝试部分核验通过，还有未提交行；status 不代执行 |
| `STOPPED` / `BLOCKED` | 漂移、过期、身份、权限、限流等门禁失败，不继续提交 |
| `VERIFIED` | 申请单和线上价格匹配，最后完整商品独立回查通过 |

`execute` 恢复同一确认计划时，已尝试请求先回查、绝不盲重发；未提交请求仍需策略和证据有效。首个写入异常停止后续提交，不为了完成批次扩大风险。`status` 可以在证据过期后核验已尝试请求，但永远不派发剩余请求。进程崩溃留下店铺锁时，先确认原进程已退出且没有在途请求，再人工处理锁，不自动清锁抢跑。

已验证不代表平台补贴报名、消费者结算价或利润保证。无真实授权 PATCH 时，只能报告离线模拟写入通过与真实 GET 通过，不能说线上写入已验收。

## API 视图与回滚

实测线上详情与申请单视图存在两类差异：展示性差异（线上多 `productStatusNew/yn`、生成的 `material.ggtImages`、SKU `skuStatus`，投影时去除）和基线序列化差异（申请单 `saleAttrs.mappingId` 填充、`material.mainImages` 结构、`goodsAttrInfos` 顺序，同一商品两视图天然不同）。因此计划在 prepare 阶段独立采集每个商品的申请单基线 `plan["applications"]`；执行时申请单视图只与自身基线比较，线上详情仍用完整 `nonprice_hash` 与自身基线比较。任一视图在采集与执行之间发生真实变化仍然阻断；不以“都是系统字段”泛化忽略变化，也不用另一视图的哈希误判本视图变更。

```powershell
python scripts/jingmai_api.py rollback-plan --profile "<Profile>" --shop-id "<shopId>" --plan "<私有目录>/plan.json" --output "<私有目录>/rollback.json"
```

只为已完整 VERIFIED 的原计划生成反向价格计划，且当前全商品价格/非价格字段必须仍等于原预期。回滚也先 dry-run、展示原价/现价并获得新令牌对应的人为确认，再通过同一 execute 入口执行；不自动回滚未知或部分成功任务，不回滚回滚计划。

## 验证与维护

`python -m unittest discover -s tests -q` 覆盖精确确认、三阶段批次、漂移/过期、视图差异、只读预检、未知写入、保存失败恢复、只读 status、回滚与旧算法兼容。发布前再跑 Skill 结构校验、私密源安装同步及安装副本测试。

商家移植只适配外部 CLI 与状态目录边界，不改变原业务执行/确认/回读算法。父级分发负责逐文件原始字节 SHA-256 校验；本子任务不提供安装器、不修改总调度。多店真实上线前仍需按店铺授权做 1/10 小样读写验收。
