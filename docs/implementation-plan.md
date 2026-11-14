# 实施计划与执行记录

2026-11-15：用户批准设计和上线实施。图片/视频模型调用来源由用户后续补充，不用内部资源补齐。目标为单一GitHub仓库安装并上手；其余业务完整推进，不缩小为mock目录。

## 执行约定
当前独立目录开发；不另建工作区、不修改内部项目。分支codex/merchant-foundation。假凭据离线测试和匿名官方公开读取；不花钱、不授权真实店铺、不做真实业务写入。

## 任务/文件/验收
1. safety.py/state.py：相对路径、原子JSON、环境过滤、脱敏。test_safety先RED；逃逸/链接/员工Key拒绝。
2. distribution.py/install.py/build_release.py：独立安装、manifest/SHA、候选激活、回执/回滚；test_distribution先RED，覆盖重复装/同名无关目录/修改/压缩包攻击/中断。
3. official.py：官方版本策略、校验后CLI和官方文档、发现配置隔离参数。test_official先RED；匿名假下载/SHA失败/default/错店；真实临时HOME运行--help/--version，不读店铺。
4. operations.py：任务范围批准、提交/unknown、原子去重、独立店铺登记。test_operations先RED；范围变更/未批准/unknown/并发只提交一次。
5. catalog.py/registry.json/SKILL.md/references：8类能力对接官方CLI/合法浏览器/上传报表/本地素材。媒体awaiting-provider；其余不因缺模型停摆。test_cli先RED，证明路由/中文onboarding。
6. workflows.py：经营报表诊断、精确规格比价/调价计划、listing-package实拍准备、素材缺口/主图详情准备、素材价格证据打包、视频文件交接。test_workflows先RED，覆盖完整SKU/真实身份/hash/QC/试听/写入另授权。
7. providers.py/video_source.py：未定模型不调用，外部凭据/schema扩展接口，指定视频源版本/发现校验。test_media先RED；内部provider拒绝/未配置不发请求/不用11190/交接完整性。
8. merchant.py/README/首次上手/例子、CI和打包审核：单仓库安装提示词；干净HOME安装→onboarding→非模型业务闭环；无内部代码/缓存/凭据/个人路径。
9. 测试→本地验证→分发/许可/脱敏审核→私有GitHub推送和发行→真实GitHub下载再安装验收。公开仍单独批准。

## 决策与进度
- 设计已批准，实施开始。
- 在当前用户独立目录工作，不另建worktree。
- 无许可证内部业务包不分叉复制；自有控制层+官方协议+宿主授权浏览器，确保非模型能力独立交付。
- 测试、真实发行安装、无授权官方CLI、商家授权、真实写入分别记录，不能混淆。

## 检查点1（继续执行，不是完成）

已实现独立安全/安装/官方CLI/任务/非模型工作流/统一入口/GitHub更新；60项自有测试和发行内容审核通过。官方0.3.7匿名下载和独立HOME init已实测。源码推送私有开发分支，尚无正式发行。下一轮继续OAuth安全worker、官方原生业务适配和完整远端发行回测，目标保持全部非模型功能上线。

## 检查点2：OAuth具体设计

决定使用任务自有后台worker、仅公开状态的本地bridge，以及同一Playwright上下文承接京麦扫码和官方OAuth；不触碰工作浏览器。身份来自该页面实际响应的精确shopName/venderId及原生API最终核验，不猜身份接口。OAuth URL和原始CLI流只在内存，日志/状态不存；只取消持有的process/browser句柄。运行时依赖在商家独立venv由Agent自动从公开PyPI安装。官方源码SHA核对发现JDO_CLI_HOME可显式指定，CredentialAccount包含profile/appKeyHash/venderId；采用merchant独立profile，强制OS原生后端不退明文。真实商家授权仍需本人扫码，开发不启动真实店铺任务。

## 检查点3：OAuth接管实现与隔离验证

已增加auth_flow/browser/runtime/manager/broker/worker及统一入口，独立PyPI运行时真实安装，真实SDK全部页面拦截的同context smoke、真实loopback/跨进程mock worker通过。未知回执、路径、错店并发、所持进程清理、前台gate和原任务恢复均有回归测试。详见auth-verification-2026-11-15.md。真实商家授权未执行；macOS官方凭据实现有secret argv风险，新授权已禁该平台。剩余原生业务适配、许可及正式发行继续，目标保持active。

## 检查点4：原生 POP 商品与价格适配

新增ProductService与字段证据解析；product/sku/health分页、原生详情、SkuJdprice平铺PATCH、批准前绑定旧价/类目及待审/线上读取、跨Profile同店未知写阻断、TTL前检后再检查、磁盘版本变化阻止旧模块写。CLI已有可执行入口；不以准备JSON替代执行/回查。所有开发测试用假店/假凭据，不运行真实店铺写入。

Ruling：同一products路径两份官方文档scopeSet描述不同；采用status文档实测的字段级枚举，不拿price文档分组造成的空壳当全字段。实际账户schema仍需商家授权后核验。风险是账户/版本字段差异；缺字段必须明示，不猜补，不反复提交。

Ruling：页面预算和回查字段限制是本地安全载荷，不是能力白名单或平台SKU上限。保留完整用户范围，按范围拆分/续读并核对来源；任何unknown阻断后续同店写。startPage>1不能单独证明完整店铺清单。修改当前独立项目，不改内部版本。


## 检查点5：价格评审闭环与凭据刷新边界

原4项重要评审缺口及敏感JSON文本残留已先RED再修复，完整干净套件150项通过，37文件包审核和ZIP安装跨进程业务mock闭环通过；详见product-verification-2026-11-15。macOS既有授权查询也可能经官方自动刷新走secret argv，统一禁用带凭据CLI而保留安装/离线能力。当前未正式发行，不把开发候选称上线完成。下一项继续合法大载荷/素材/上新原生适配；真实写入及模型来源仍分别受授权与待确认约束。


检查点5远端回测：实际私有GitHub代码commit b39c25463c7bf1de09408f5dd6197c18db965d29重新克隆、重建hash一致、fresh HOME安装/onboarding/安装后业务mock和150项套件通过。仍无正式Release；大载荷下一步：先审计官方同版公开源输入/日志/自动重试/凭据链路及deprecated风险，不能通过app-secret-stdin误传图片，不把未实施方案记成能力。


## 检查点6：官方大载荷传输

已经实现版本/SHA/批准绑定的官方同版源码stdin薄适配：源码和载荷仅内存/管道，不复制源或重新实现签名，sourceStatus deprecated透明；小载荷仍binary，unknown不fallback。独立评审3项重要问题先RED再修复，worker完整店铺身份与同一冻结auth上下文签名seller GET、成功回显与秘密JSON键过滤。实际公开source/binary校验+真实隔离子进程合成900KB请求smoke已跑；真实商家Credential读取/刷新或图片上传仍未跑。完整验收和GitHub回测见transport-verification-2026-11-15。下一项媒体空间/分类和原生上传绑定、完整SKU上新，尚未整体上线。

Ruling：source由官方策略声明deprecated，仅采用已审核同版/SHA且不落盘/不分发；失败/撤回/新版本暂停该transport，不能静默换成不支持的来源。成本是大载荷可能等待新审计，第三方许可未重授。

minor (deferred)：worker没有第二次断言JDO_ENV=prod，正常parent已强制；绕过parent独立启动不是支持的商家流程。


检查点6回测：私有GitHub source commit 387e66fded031b2c0921f8603cb9395112939c8a实际重新克隆；重建SHA一致、40文件审核、fresh HOME安装/onboarding、安装后签名/身份GET大载荷mock和价格mock、170项全套通过。继续原生媒体上传/绑定/上新，不把transport smoke当上传成功。
