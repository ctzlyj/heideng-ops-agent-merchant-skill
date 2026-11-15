# Agent命令约定

所有命令由Agent定位实际安装根目录后执行，路径使用绝对路径并正确引用，商家不复制命令或填写凭据。统一入口scripts/merchant.py默认输出UTF-8 JSON，exit2表示缺条件/阻断，不是成功。

| 命令 | 用途 |
|---|---|
| onboarding / doctor | 中文首次上手、本地状态；doctor --install-cli才下载官方CLI |
| route <自然语言> / catalog | 目录发现，不限制合法目录外能力 |
| official-doc <skillId> | 校验官方协议文档，按实际字段组装请求 |
| shop-connect --profile --shop-name --vender-id | 实时venderinfo核验后绑定明确POP店铺 |
| auth-plan --profile --shop-name --vender-id | 新授权的同会话安全接管计划；目前不是已完成的OAuth签发 |
| inspect-source --source --sheet | 查看CSV/JSON/XLSX列名/范围，不猜数据口径 |
| diagnose --source --output --mapping | 映射真实列名后诊断；部分缺项明确标记 |
| material-audit --source --output | 保留所有SKU，199个SPU一批列缺口 |
| compare --source --specs --output | 精确结构化规格与原生到手价证据的TOP10 |
| prepare-listing --product --source-root --output | 实拍、类目和全部规格转listing-package，无伪造SKU或链接 |
| package-snapshot --snapshot --output | 整理真实采集的SKU顺序、价格证据、素材 |
| attach-video --manifest --video --cover --review | 已有视频真实hash和审核交接，无生成调用 |
| task-plan --profile --operation --verification | 对应官方真实接口的任务计划文件 |
| task-approve --task-id --fingerprint --confirm | 仅用户已明确批准后记录一次精确范围 |
| task-execute / task-status | 执行/只读状态，unknown不能重提 |
| task-readback --task-id --query --expected | 官方GET核对目标状态，不以文件/exit0代替 |
| update-check / update-apply | GitHub发行发现、候选SHA校验和空闲切换 |
| video-source-status / video-source-check | 指定视频repo的来源记录/发现，不启用生成 |
| media-status | 明确图片/视频模型来源待确认 |

XLSX可选openpyxl：由Agent在独立商家运行时从公开来源安装；多可见Sheet须选择真实源Sheet，公式无缓存值不能造结果。不能往全局员工环境安装依赖。

官方CLI调用固定生产环境和官方元数据入口，禁default Profile，禁止CLI的mock-token/print-code/code等不安全OAuth选项。大载荷在提交前按官方同版stdin薄适配，不截body；接口权限错误不能换工具绕过。浏览器只有独立合法通道和对应范围授权时才适配，未知先查原回执不重提。

## 回查契约

写入计划应在批准前附verification JSON：query（真实官方GET）和expected（原目标商品/SKU、申请/操作关联字段、终态及最终值）。它进入任务fingerprint；task-readback传入的query/expected必须完全匹配原批准范围，不能事后换无关商品来关闭任务。无verification的写入不能被通用回查标记完成，需先核对原回执并补业务原生适配，不能伪造。

反例：调价提交超时后，无关商品正常或目标商品当前价格相同，均不能证明原提交已终止。目标匹配会记录targetStateVerified，但原unknown仍保留，继续阻断重提与新写入；只有能关联原请求的正式平台终态证据才能进一步解除，不提供删除状态/换工具重提的捷径。

## 原生商品与两阶段改价入口

商品/SKU/健康分、price-plan/price-status以及待审/线上两阶段验收详见 references/native-products.md。优先使用该高层入口，不手拼旧PUT价格接口。

- product-list / sku-list / health-list / product-detail：实时同店读取，不拿旧GET任务缓存当新数据。
- price-plan --profile --product-id --changes：读取真实详情后生成精确京东价计划（不写店）；changes是本地JSON数组。
- price-status --task-id --refresh none|pending|online：本地证据/原申请单/线上分别查询，不重提。
- task-plan额外支持--precondition、--online-verification：两个文件也进入fingerprint，不能批准后换字段。
- task-online-readback --task-id：只读取原批准前绑定的线上验证范围。
- official-doc额外支持--reference references/<file>.md与--refresh：从当前官方策略SHA取得完整参考文档，不只入口。


## 大载荷（无需新的商家命令）

原task-plan→task-approve→task-execute自动按实际commandline长度在提交前确定官方binary/stdin。必须查看scope.officialExecution（版本/SHA/sourceStatus）并绑定原fingerprint；不把源声明deprecated隐藏。stdin规则和验证边界见official-transport.md。所有status/readback只查询原任务；未知结果不得换transport重放。


## 原生素材与结果ID绑定

material-zones/material-categories/material-images/material-detail，material-upload-plan/material-upload-status，以及task-result-readback，详见native-materials.md。task-plan额外支持--result-verification，引用只解析原已知回执ID。CLI省略imgBase64并显示SHA，真实请求只在本地状态/传输管道；素材保存不宣称商品绑定/线上生效。

## 完整编辑schema与无损本地草案
product-schema --profile --product-id；schema-capture-status --capture-id；schema-image-draft --capture-id --changes；schema-draft-status --draft-id。来源、精确slot和未完成发布边界详见native-product-schema.md。只有商品详情/完整SKU分页/唯一编辑schema有限次观察一致才生成capture；未知字段不删、全部SKU不变、草案不提交。

## 新品校验/提交入口
publish-categories、publish-brands、publish-context；publish-validation-plan --profile --manifest --schema --spec-map --asset-bindings；publish-validation-status --task-id；publish-plan --validation-task-id；publish-status --task-id。详细字段来源、校验与条件提交的明确许可、同源包去重和未验证线上边界见native-publishing.md。prepare-listing保留完整sourceProduct；源码、规格、真实图片不可用空壳默认值补齐。

既有商品整版编辑见 references/native-full-edit.md：schema-edit-baseline、schema-edit-validation-plan、schema-edit-plan、schema-edit-status [--refresh]、schema-edit-online。输入由 Agent 从当前原详情和模板生成，商家不手填 JSON；两步 POST 均需精确批准。

`schema-compile --capture-id <id>` 自动 materialize 原规则与全 SKU 来源；`schema-edit-prepare --capture-id <id>` 自动编译并建立/复用来源基线。商家不手填 JSON；详见 native-template-compile.md。两者不提交商品写入。

原生 SKU 缺失素材槽位：sku-material-audit、sku-material-plan、sku-material-approve、sku-material-execute、sku-material-status。先读 references/native-sku-materials.md；计划一次范围批准，各50SKU块逐一留账/回读，不重绑旧槽位、不替 unknown 重提。

全店在售来源审计：sku-material-shop-audit / sku-material-shop-status / sku-material-shop-rows。默认查询一次完整原生health来源，信息分和素材源的完整性独立记录，摘要不输出数千ID；全明细在原指纹捕获文件与分页接口，详见 references/native-shop-material-audit.md。

原生已有视频计划的本地取消：video-delivery-cancel --session-id --fingerprint --confirm。仅明确取消且尚无业务尝试时可用，保留原计划和独立取消证明；unknown/allocated等不可取消，不删除状态或换ID重提。运行时版本与更新门禁见 references/native-video-delivery.md。

整店已准备好素材的一份根范围：shop-material-plan --audit-id [--changes] [--target-slots]；shop-material-approve --plan-id --fingerprint --confirm [--ttl-seconds]；shop-material-execute --plan-id；shop-material-status --plan-id [--refresh]；shop-material-rows --plan-id [--view coverage|chunks --page --page-size]。Agent组织清单、批准与余缺说明，商家不手填JSON；先读 references/native-shop-material-execution.md。独立父批准/原件/全覆盖摘要，不把部分成功和平台信息分混淆。
