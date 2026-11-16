# 浏览器短标题接口证据与边界

当前流程见 short-title-import.md。商品列表URL：`https://wares-jdm.jd.com/ware/wareList?activeTab=OnsaleWare&businessModel=0`。

可观察接口：dsm.base.service.file.upload、dsm.product.manage.view.batchJobService.createImportJob、dsm.product.manage.view.batchJobService.queryByPage。复用当前店铺真实页面请求，不复制Cookie，不读取凭据库。

文件上传返回200只证明文件传输；createImportJob返回200只证明接受创建；导入记录行的任务ID与成功/失败数证明处理结果；最后health-infos证明目标短标题缺项是否清除。这四种证据不能混用。

记录只保留任务ID、SKU范围、文件sha和脱敏状态，不保存原始网络头/凭据响应。脚本固定等待后返回submitted的旧行为已移除。

2026-10-28只读核验：queryByPage使用data.batchJobRecordDtoList，实际任务字段jobExecId；jobId是类型ID。恢复无任务ID记录时必须关联上传对象hash和jobExecTimeStart，不能把列表唯一新ID当成本次回执；签名URL仅在内存关联，落盘只保留对象身份hash。
