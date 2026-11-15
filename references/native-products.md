# 原生 POP 商品、SKU、健康分与京东价更新

商家只说目标；下列命令均由Agent从实际安装根目录用绝对路径执行。Profile必须来自ensure-shop的实时核验结果，不让商家输入、不用default、不扫描员工配置。

## 查询与完整性

- `product-list --profile <profile> [--filters <json-file>] [--page-size 20 --max-pages 100 --start-page 1]`：原生商品分页，字段级scopeSet为productId/productName/productStatus。
- `sku-list --profile <profile> --product-id <actual-id> [...]`：某个真实商品下的全部SKU分页；不猜ID、保留原生顺序，回包productId须匹配目标。
- `health-list --profile <profile> [--filters <json-file>] [...]`：商家合法权限的原生健康分/待提升项；缺权限不转员工黄金眼/EasyBI。可据实际字段整理素材缺口，新增图片仍awaiting-provider。
- `product-detail --profile <profile> --product-id <actual-id>`：原生完整详情，scene=pop；定位真实类目、SKU及priceInfo.jdPrice。

上述读取不复用旧GET任务缓存，每页均实时核对同店身份。complete只代表从第1页覆盖本次API返回的记录数，不代表原子快照、也不保证所有业务字段非空；仍检查列缺项。startPage>1的segmentComplete只代表该续读段到末尾，不能把缺少前页的段说成全店齐全。重复ID、总量变化、失败或达到本地页预算返回partial与nextPage；保留已读事实，不通过跳过异常页造“全部完成”。续接时核对同查询/每页大小/来源时间及跨段ID重复，不能直接拼出未经验证的快照。

字段约定来自当前校验官方文档；products的另一文档有baseInfo等分组写法，与status文档实测的字段级枚举存在差异。本实现采用字段级枚举。若真实回包缺字段，应查看本次官方协议/账户实际schema，不凭空把空壳当完整资料或反复换参数重试。

## 改京东价，不是改到手价

1. 先定位实际productId及SKU。商家若给同款比价目标，必须保留精确规格和逐SKU到手价口径；不能把竞品手价直接当本店jdPrice，也不依图片猜规格。
2. Agent整理changes JSON数组：每项只含skuId、jdPrice；可加expectedOldPrice表达用户已经确认过的旧价。价格是精确元/分，不接受NaN/布尔/负数/零、不自动舍入。
3. 执行 `price-plan --profile <profile> --product-id <actual-id> --changes <json-file>`。它只读取原生详情、校验商品/类目/SKU归属与旧价并生成计划；不写店铺。展示完整店名、venderId/Profile、productId、每个SKU旧京东价→新京东价与不变项。计划已经包含后续所需的旧价/类目前检、待审回查、线上回查及完整fingerprint。
4. 如果全部目标已是当前价，结果already-current且无写任务，不能再为“成功回执”提交一次。对超出CLI载荷/回查字段上限的请求按实际范围拆计划，不把本地限制说成平台不支持全部SKU；必须完整保留用户范围，拆分后仍要一次展示/确认所有计划。
5. 得到本次具体范围的真实用户批准后，执行 `task-approve --task-id <id> --fingerprint <fp> --confirm`，随后 `task-execute --task-id <id>`。开发/安装授权不是店铺写入批准。相同范围不重复索要确认；范围/旧价/类目/版本发生变化或授权过期则原批准不能沿用。

原生请求使用PATCH product-applies/{applyId}；POP三处ID均对应真实productId，body两处字符串、一处数字；opType=3、scene=pop，SkuJdprice是字符串化单组件JSON。不能改成旧PUT products捷径、包装request层、传数组或拿stock/status接口改价格。字段是否支持以本次平台回执为准，被拒不换组件盲试。

## 两阶段回查，不重复提交

- `price-status --task-id <id>`：本地任务与已有证据；来源时间分别为pendingObservedAt/onlineObservedAt，不冒充刚查过线上。
- `price-status --task-id <id> --refresh pending`：只读取原计划绑定的product-apply/{applyId}，精确匹配各SKU待审值；重复refresh确实再次读取，不重提。
- `price-status --task-id <id> --refresh online`：只读取批准前绑定的商品详情，核验全部原目标（包括当时不变的SKU）的线上京东价。
- 待审值确认表示申请单目标值已有证据，**不是线上价格已生效**。bossAuditStatus=-1是正常的未进入采销审核流状态，不能当失败重提，也不能把它当线上已生效；11为观察到的审核驳回。不能死等10来替代实际线上读取。
- 原提交unknown时，pendingValuesMatch/onlineValuesMatch即使为true，phase仍unknown，不能证明原请求终态、重提、换Profile或接着执行事先prepared的另一写任务。同一venderId/shopId的未解决写入跨Profile阻断。
- 类目/旧价在批准后变化、前检期间批准过期、磁盘版本已变或错店，提交前拦截。该前检不是平台事务/CAS保证；发生平台并发改动时仍按原回执与实际读取核对，不夸大原子性。

## 官方协议与验收边界

查看本次官方文档：`official-doc jdo-product-update --reference references/update-api.md --refresh`，必要时同样读取components.md；文件必须出现在官方版本策略且SHA匹配。公开文档不等于所有账户都有API权限，不用真实凭据dry-run输出认证头。

当前实现按已核验官方0.3.7协议并通过离线/mock业务链、身份/并发/恢复回归。未执行真实商家查询、改价、上架或付费生成；不可把本地回归称为平台实机验收。其余合法POP任务仍可查官方资料、组合宿主能力，不把本页变成能力白名单。

## 大范围价格本地预算
旧18000字符guard已删除：官方transport按实际Windows argv选择binary/stdin。当前完整单任务最多1000条SKU价变更；每段验证最多1024字段/256KiB是本地证据预算，不是京东平台SKU上限。超过预算须保留完整用户目标并显式分段、逐段新鲜核验和批准，任何unknown阻断同店后续写入；不截断SKU、不只回查第一条。
