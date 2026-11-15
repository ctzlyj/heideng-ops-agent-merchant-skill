# 短标题完整规划与中间模板（自动导入尚待接入）

商家说“维护这家店全部在售商品的短标题”，Agent先复用native-shop-material-audit.md完整在售/兄弟SKU与完整原生health来源。不能按健康分或是否有health行选库存；素材读取失败不等于标题信息不可用。原health里的hasShortTitle按原SKU/父关系归属推导，问题未知、无问题、离线兄弟与待稿分别报告，不把派生布尔标志当来源。

## 当前可执行的前置阶段

- short-title-plan --audit-id <原ID> [--changes <Agent生成的文件>]：每稿为productId/skuId/shortTitle/review=passed，来自原实际商品/规格，经宿主真实审核；商家不手填JSON。仅原在售且明确有标题问题、原名字已知的SKU接稿。默认完整范围始终保留，不传changes也可看全部待稿/未知。
- short-title-status --plan-id <ID>：紧凑历史摘要，onSaleSkuCount、offSaleSiblingCount、nativeIssueCount、reviewedCopyCount、awaitingCopyCount、unknownTitleIssueCount、batchCount。1份稿或1页不表示全部店铺。
- short-title-rows --plan-id <ID> [--view coverage|chunks|siblings] [--page 1 --page-size 50]：分页看原名字、问题、稿和5000行批次；siblings视图展示完整离线兄弟及excluded-offsale状态，coverage默认仅在售，不以计数代替明细。
- short-title-workbooks --plan-id <ID> --template <当次商家模板或测试合成模板>：只生成Agent的中间产物，按5000行/5MB核对，SKU为精确文本。保留说明/表头/格式，删除样例和未再引用的共享字符串。宏、外部/活动数据关系、DTD/实体、公式、重复/穿越条目、错误表头及未知多表拒绝；实际workbook/worksheet关系和content types必须精确绑定，兼容性命名空间声明保留。

当前全部返回planningOnly=true、writeExecutionAvailable=false、imported=false；模板编译同时templateOriginVerified=false、readyForImport=false。**这些命令没有导入/approve/execute，也不应给商家一张表让其默认人工上传**。内部缓存xlsx不进入本仓库/安装包；不使用员工浏览器、O2模型或Key。缓存说明不能冒称当前平台规则；当前1–30保守加权、16–28仅文案建议，不虚构16下限，空白清空不支持。新稿去重是默认文案质量约束，不称平台强制；与未知原短标题去重未验证。

## 仍必须完成的下一阶段

当次任务自有浏览器同店身份/模板来源、精确根批准、仅短标题抽屉上传/创建实际实例ID、独立attempt/ack/anchor与unknown只查不重传、逐行结果及仅确认失败行补导、原范围回读和更新门禁。参见docs中的short-title-import-design/plan；这些不是可选范围。jobId任务类型不能当实际实例ID，行接受/文件生成不等于生效或分数刷新。真实商家/当前页面接口、许可与模型来源均不由本阶段合成测试证明。

已开发B1内部浏览器source adapter，见 references/native-short-title-browser-source.md；尚无CLI/worker/上传批准，不能称自动导入已可用。
