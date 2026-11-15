# 全店在售信息健康分与素材来源审计

商家只需说“检查这家店全部在售商品的信息分和素材缺口”。Agent 执行本入口，不要求商家输入命令、SKU清单或JSON。本能力是**只读审计**，不是生成、上传、修复或绑定任务。

## 完整来源而非一页结果

- 先读本店在售商品（原生状态103），再逐商品读全部兄弟SKU；离线兄弟保留，不把“有分值的SKU”当作库存。
- 原生health-infos完整分页只收集一次数据集，保留healthScore及improvementList。官方名称为商品信息健康分，与页面commodity-score逐行等价性仍未实测。
- 读取全部兄弟SKU的31/32/33/36图片和1002文字素材，按1000个本地输入段、50个原生SKU查询批次处理。1000不是全店截断上限。
- 商品/SKU/health分页必须有稳定reportedTotal、无重复/外店ID与父商品矛盾。结束时再次核对在售商品及完整兄弟SKU集合，允许排序变化；集合/状态/名称漂移或查询不完整时complete=false。
- 原生素材GET能力卡片及有限Schema规则核对，结束时再查卡片；不支持的卡片/结构不会转员工SDK、内网SSO或公司Key。
- 收集期间持有商家安装锁，阻止商家包在任务中被更新。远端仍不是事务快照；所有读数只是startedAt到finishedAt这一窗口的证据。

## 分值和素材分类

分值原生0、0–89低分、>=90、缺失、无效、未取得和未请求分别保存，**不补0**。完整health来源未出现的SKU可标缺失；health来源不完整/无权限或未请求时，不出现的SKU是unobserved/not-requested，不当作已证明缺失。

健康行父商品与库存不一致时，保留原来源行供诊断，但不把它的原分值、提升建议或短标题问题归给当前SKU。未匹配到观测SKU的health行，只有库存集合已完整且前后稳定时才可说“在当前范围之外”；否则外部分类为null，明确仅是“未匹配当前已观测集合”。

真正不存在的槽位、已存在空内容、待审3、通过4、驳回5以及不明状态分开。素材段读取失败时missingSlots=null，不推断“所有图都缺”。高分SKU有素材缺口仍报告，不因分值>=90漏掉。短标题hasShortTitle只根据已关联的原生improvementDetail，不能凭标题长度猜测平台问题。

空在售库存经前后完整商品读取证明后，返回noWorkInScope；不为零目标强行请求无关health/素材权限。未读下游的来源标记仍保留，不伪称全局health已经查询。

## Agent 入口

- `sku-material-shop-audit --profile <profile>`：默认阈值89、最多10000商品/100000兄弟SKU/1000分页；预算不够时明确拒绝或不完整，不截断后宣称全店完成。需要只看素材可显式no-health，不伪装为已查分值。
- `sku-material-shop-status --audit-id <id>`：原捕获摘要与完整范围计数。它是历史捕获，不重新查询远端，也不输出数千ID造成工具截断。
- `sku-material-shop-rows --audit-id <id> --only <filter>`：过滤all、low-score、gaps、pending、rejected、unscored、short-title、unobserved；每页默认50、最大200。默认只显示在售SKU，include-offline可查全部离线兄弟。

`pageIsWholeSelection` 是完整捕获中当前筛选的覆盖；`pageIsWholeShop` 必须覆盖整个已捕获兄弟集合，不能因默认隐藏离线兄弟就宣称全店。total、nextPage和rowScope始终说明当前分页选择；全量来源在reportPath的原指纹捕获里。

## 读完后的动作

Agent 根据完整捕获整理全部SKU与原商品关联、低分/未知分值、素材缺口与审核问题；展示可执行方案。新图片/视频源继续等待负责人配置，先复用可用合规素材。真正缺失槽位的上传/绑定使用native-sku-materials.md独立写入链路，必须有明确批准、原上传回执和当前SKU/素材再核对。驳回修复、短标题导入和全店写入编排仍是后续步骤，不把此审计当维护成功。

当前为合成/独立安装验证等级，未实测真实授权、权限、卡片格式/业务数据、平台审核或分值重算。writesPerformed=false，scoreRecalculated=false；不能据此宣称“全店信息分已提高”。
