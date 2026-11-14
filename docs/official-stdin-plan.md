# 官方大载荷 stdin transport 实施计划

> 使用executing-plans与TDD本地执行，完成后一次有界独立评审。延续已批准独立商家架构，不新建聊天/worktree。

**Goal:** 已批准的图片base64/大上新JSON不进入OS argv，不重新实现签名、不因native失败重提；商家仍只安装本仓库。

**Architecture:** 小载荷继续官方校验二进制。大载荷在提交前选定官方同版公开Python源的stdin薄适配，策略版本、二进制安装回执和源码SHA一致，源码仅内存。源码声明deprecated必须明确暴露；仅本轮实读静态审核的0.3.7/SHA可执行，未来版本先审计不静默替换。隔离Python -I子进程通过官方main/parser/cmd_invoke执行，不复制签名算法或源码。Windows原生Credential Manager；macOS继续禁用凭据执行。

**Spec:** 原始目标文件、docs/migration-design.md、docs/implementation-plan.md及官方SHA核验资料。Key不进argv/源码/日志/Git，真实写入另授权。

## 文件与契约

- 新heideng_merchant/official_transport.py：确定载荷路由、审核源清单、同版SHA校验与执行回执。
- 新heideng_merchant/official_stdin.py：有界stdin envelope、二次验证源码和本地二进制、内存官方parser调用、捕获并脱敏输出，无源码落盘/遥测/重新授权。
- 修改official.py：plan_execution(operation)返回明确binary/stdin契约；invoke(expected_execution=...)提交前核对；输送input=bytes，OS argv只有python/worker参数，native失败不fallback。
- 修改operations.py：支持真实client契约进入scope fingerprint；准备与执行前检查版本/源、审批过期；任务保留实际transport版本回执。fake client无该接口继续离线测试。
- 新tests/test_official_transport.py、test_official_stdin.py、test_transport_binding.py与smoke_official_stdin.py。
- 新references/official-transport.md并更新commands、SKILL、README；不分发官方源。

## Global constraints

官方策略来源仅mcp-open.jd.com；source path仅cli/jdo-cli；source version必须与已验证binary receipt version一致；source SHA必须为本地审核清单中的精确值。业务JSON上限8MiB、source上限2MiB、stdin envelope上限16MiB，仅本地安全边界，不是平台SKU或图片上限。读取来源失败/版本冲突前置拦截，不启动进程；worker失联/超时/无效响应保持unknown，不换transport重发。

## Review focus

- source或binary更换与批准后的任务范围不可串换。
- unicode/quote使Windows实际commandline超限，应在派发前选择stdin。
- 官方命令错误echo凭据和完整request：两条输出流仅内存捕获，秘密收集后脱敏；外层不返回原stderr。
- POST/PATCH只有一个业务提交意图；官方GET transient重试允许，写transient或unknown不重试；业务auth失败不能因宽泛关键字重复写。
- body的嵌套JSON敏感键仍前置拒绝；未授权/错店/macOS不运行；源码无落盘或telemetry。

## Tasks / tests / ledger

- [x] 1. RED parent路由/版本/hash/无argv/未知不fallback测试；实现路由与source验证；GREEN。
- [x] 2. RED worker业务输入/源码替换/捕获脱敏/无落盘/自有Credential环境/只执行invoke测试；实现stdin driver；GREEN。
- [x] 3. RED Operations任务fingerprint与提交前版本变化；实现plan_execution绑定；GREEN。
- [x] 4. 真实SHA源仅内存，通过真实独立Python子进程+拦截全部业务网络+合成凭据跑大载荷smoke，检查官方签名请求解析/无重复写；不是真实merchantAPI。
- [ ] 5.（代码review/修复及170项全套、40文件审核、安装后smoke已完成；私有推送/回测待收口） 一次有界评审，重要问题RED→GREEN；完整clean suite、包审核、安装、记录、私有分支推送和实际GitHubclone回测。

## Ruling

使用policy中声明deprecated的同版公开源作为大载荷兼容transport，而非默默替换常规二进制；版本/SHA严格审核、源码不复制发布、parser和签名仍官方；代价是该源未来撤回或变更时大载荷暂停，不能宣称享有独立第三方源码再分发许可。此方案不代表真实商家写入已实测。


## 已完成证据（评审与全套未最终收口）

1. parent路由/源版本/SHA/quote溢出/无argv/超时无fallback共7项GREEN。
2. worker源替换/二进制替换/环境/输出捕获脱敏/无源码落盘/写不重试/审批期限共5项GREEN。
3. Operations契约fingerprint/旧批准换源拦截/最终deadline传递3项GREEN；原operations12项通过。
4. smoke真实同版官方source/binary（SHA正确）+真实Python -I/-B，900074-byte业务body，业务网络拦截与合成认证；success/auth-marker/lost-response各一业务HTTP尝试。默认driver协议入口在空HOME拒绝，源码/原stderr无落盘。不是商家Credential条目读取或真实上传。


## 单次独立评审及一轮修正

review：无Critical，3 Important、1 Minor。旧prepared真实任务缺officialExecution、预检期间换店、成功输出含原载荷/已知秘密JSON键，均先RED后修复；33项定向回归GREEN。修正包括缺契约旧批准拒绝、预检后核身份和底层expectedShop传递、worker同一冻结auth上下文签名查询seller-info后才写、共享redact处理秘密键及publish_response去请求回显。源的实际HTTP仍只使用官方实现。没有另开第二轮review；最终修正由本地回归/完整套件/实际SHA源拦截网络smoke验收。

minor (deferred)：worker未二次断言JDO_ENV=prod；parent强制prod，正常路径未观察到错环境提交，暂保留为纵深防御项。代价是绕过正常parent启动driver时缺少该断言，不能把driver独立启动列为支持的商家流程。
