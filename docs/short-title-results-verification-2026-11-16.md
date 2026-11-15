# C1/C2 原实例短标题处理结果私有研发验收（2026-11-16）

## 结论和明确边界

代码 `ac915588d01e4aee21706878e2122dee23283e7e` 已在本地与**实际私有 GitHub fresh clone**两种环境分别通过 **650 项全套 + 7 个 installed smoke**。本次包 **104 个文件（103 个受manifest校验的源文件+manifest）**，SHA256 `52e7fbd0e227b72fcda76a44ed33ff3b24c2a3213a7375f74d5fa250b4c1397e`。这不是商家完整自动化上线、公共发布、真实平台验收或商业化许可。

C1/C2接通原instance/upload对象/时间/结果源绑定、bounded原文件GET、完整逐行处理回执和独立observation/receipt/head。`processing-completed-awaiting-title-verification`及`rowResultsVerified`只证明原范围处理结果；实际短标题/审核/health/门户证明、确认失败专属修复、持久owned worker/merchant execute入口仍是**必须完成**的工作。`imported`、actualTitlesVerified、healthVerified与retryAuthorized不推断为true。

## 实际验证

- 完整650是原601基线+49新持久方法：15结果文件解析、7 bounded GET、18原生结果与原件/恢复边界、4 RPC入口、5同店隔离；不是只执行新测试。
- 七个installed smoke：C1/C2结果、B2导入API、B1browser来源、A1/A2规划、整店素材修复、整店素材执行、native update gate。
- 本地同原进程执行，源文件集合/hash冻结；实际GitHub克隆固定同commit，fresh venv/public PyPI测试依赖、fresh HOME offline安装和installed onboarding，重建包hash一致，全部测试/七smoke后clone干净。
- 包审查personalPaths/credentialPatterns/unknownFiles均0，范围仅审查包，不证明第三方runtime或真实店铺。
- 独立bounded复核10方法、45cases、0fail/error/skip；18个合并记录源/测试hash与当前相符。原C2 3项Important均消除；额外RPC sidecar9方法和同店门禁2项P1的5方法复核分别通过。旧bug-confirming probes保留，不把它们的pass当安全验收。

## 已复现并修正

1. 任务行计数不再接受1.5/1e3/1/100的integer前缀，也不忽略坏重复label；完整token和每次label都检查。
2. head先核对真实存在/regular file/JSON对象及strict整数sequence；既存null、directory与bool head/receipt不当“缺失”。仅genuinely absent first-head或合法stale-head/receipt从完整原件重算。
3. currentTaskAnchorMatched与currentResultSourceVerified分开，缺URL/pending/GET错误/坏bytes不称结果源已验证；当前读范围另列currentResultReadBatches。
4. native结果源hash与download对象hash独立核对；bounded DOM行摘要补充原件。未知/丢失前缀/孤立/改动证据拒绝，不以换source或新计划绕过。
5. C1仅识别原批次完整明确成功/失败，不从totals或非成功文本推断失败；numeric/scientific SKU和未知表结构不默默规范化。现支持历史审计的三列/单表，真实平台输出形态仍未实测。
6. 曾因直接import旧TestCase误发现32而不是新9，确认发现集合后仅停止own原进程修正module alias，不是因为等待超时重启；真正9RED及后续owned风险RED/GREEN另保留。
7. installed旧B2包缺C1模块的RED确认不是从源码fallback加载；重建新包后明确每个模块来自installed目录。业务断言未减弱。

## 安全与尚未验收

所有店铺/身份/浏览器factory/DNS/HTTP/模板/批准是synthetic，实际browser未启动；真实OAuth、authenticated jdo info、商家网页/API/写入、付费模型、消息均未执行。原结果bytes仅内存解析，signed URL/JSON/DOM原文不存状态/报告；GET不加Cookie/Authorization，不读company keys、不用代理或redirect/retry。Task fields、列名和DOM文法是历史源码审计，不代表当前全平台可用。

内部仍**1.5.4/13692b759bd52e35c3670cf8fad5330e1bf2b576**且clean，未修改；视频上游仅记录**已审计0.3.0/29548089f7b71ac77ddb584caac0966a98df24ab**，不称latest。生成来源待用户决定。整体goal仍active。

## 复现说明

checkout上述代码commit，fresh venv按tests/requirements.txt从public PyPI装测试依赖；运行tests/run_offline.py全套和上述7个tests/smoke脚本，build_release/audit_release核对包，offline install用精确SHA并从installed scripts/merchant.py运行onboarding。状态只是历史原件，实际效力须C3另核；详细stage receipts/counts和范围见同名JSON。
