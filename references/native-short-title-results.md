# 原实例短标题处理结果只读API（C1/C2，完整商家闭环尚未完成）

这不是导入执行、标题生效或自动重试入口。B2依然需本次精确root写入批准；C1/C2只读获取原任务的处理结果，不调用模型、不上传/创建任务。持久owned worker/merchant execute CLI、实际短标题/审核/health/门户独立回读和确认失败专属修复是后续必须完成部分。

## 读取及原来源

- Agent在同进程原 owned ShortTitleImportBrowser会话中调用 ShortTitleImports.collect_results(importId,browser,batch=None)。batch显式指定时必须是原root内编号；未指定只读已原件anchor的批次。
- 当前同店身份、原actual实例、原upload对象hash与原创建时间都须一致。queryByPage只是一页，未出现原实例不证明任务不存在；jobId不当实例ID。
- 原抽屉tbody任务行必须唯一匹配actual ID且拥有明确唯一终态、成功和失败计数，计数和等于原批次行数；不猜JSON计数字段，不把未完成/处理中称已完成。
- 只从同一原生任务行的jobExecFileRst读取结果URL；完整URL仅browser内存。薄transport对这个已观察来源做bounded public HTTPS GET：固定已解析公网DNS、TLS主机校验、无Cookie/Authorization/环境代理、无redirect/retry、identity编码、受支持XLSX/octet-stream MIME、5MiB完整byte界限。不猜新后台REST或复用内部登录态。
- 存原任务页、任务行摘要、身份hash及独立结果源hash；download对象hash必须等于原生来源hash。结果bytes仅内存解析，不把原表/JSON/DOM/签名URL保存到状态或报告。
- 原JSON字段与结果表三列是已核对历史源码契约，不是当前真实平台实测。真实UI/schema/模板/MIME/类别/规模及下载可用性仍需本人授权验收。

## 逐行结果与状态

- 当前受支持首行表头恰含 SKUID/执行结果/失败原因，每列一次，单工作表安全XML/ZIP。SKU必须真实文本，拒绝numeric/scientific/重复/遗漏/原范围外SKU、公式/外联/宏/DTD/炸弹与未知表结构。
- 原<=5000批次SKU须恰好一行；按原批次顺序回报。只把字面“成功/失败”识别为确认处理结果，其他为unknown，不能拿总数推断未识别行。
- 原任务计数与完整结果成功/失败计数相符。未知行使完整结果未验证；确认失败候选不构成重试批准，当前retryAuthorized始终false。
- 状态processing-completed-awaiting-title-verification与rowResultsVerified仅说明全部原批次处理结果已明确。imported/actualTitlesVerified/healthVerified仍false，任何实际原标题/审核/分数/生效均不推断。
- short-title-import-status读取历史原件，不自动联网。short-title-import-rows --view results按原scope分页，附proposedShortTitle与outcome/reason/instance/sequence；提案文字不是实际title。

## 原件与恢复

独立append-only observation、receipt哈希链与head三方核对。丢原observation、篡改、断前缀、孤立文件或head矛盾阻断，不能以变更文件名/source/新计划绕过。只有原observation完整、确定receipt/head可重算的中断可在同根锁下恢复账本；没有原表或证据时不伪造其结果，更不重发写任务。

每次新观测保留历史；新状态pending/unknown不重投。已有upload被接受而尚未尝试create时，结果读取不导航、不销毁original live binding。browser仍持install.lock，本线程真实witness才可复用；即便处理结果完整也不释放update/rollback门禁，C3/worker的完整证明仍待实现。

currentTaskAnchorMatched只证明本次读取的原task tuple匹配；currentResultSourceVerified还必须存在经过核验的原生结果源hash、对应GET/bytes与已解析结果证明。缺URL、pending或GET失败不标来源已验证，currentResultReadBatches注明本次读取范围；status仍只返回历史原件。

## 原生入口及同店未决任务隔离

file.upload / batchJobService.createImportJob / batchJobService.queryByPage仅支持已审计的短名与对应完整dsm.base.service.file.upload / dsm.product.manage.view.batchJobService.createImportJob / dsm.product.manage.view.batchJobService.queryByPage。每个响应必须只有一个method值，仍核对原host/path/main-frame/current-request，不作substring或未知namespace推断。真实当次平台兼容性仍需授权验收。

原生短标题已attempt/unknown/submitted而C3尚未验证时，同profile或同venderId+shopId的其他写入工具和已准备的另一根也必须先恢复原任务；不能换新审核/新source绕过。原协调器仅排除自己已核对的root，独立一次dispatch规则仍保留，readonly恢复/结果读取不争写入许可。不同真实店铺不因合法另一店原件被误标同店；不明孤立原件需先恢复。处理结果不是释放此隔离的依据，C3/失败子计划门禁须继续实现。

同店门禁检查已有root下C2原件内容和原anchor，不只检查目录归属；本root写入路径也必须在排除自己前校验完整C2 log。仅删除B2历史而保留C2原件会阻断，不能先重复写再报完整性错误。原只读recover/collect仍可从完整原件恢复确定的receipt/head。
