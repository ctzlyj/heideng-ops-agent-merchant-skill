# 商家只读诊断：成熟复用

来源 `ctzlyj/jd-store-diagnosis` / `bc5a0fb5f01f0867a269388e076539a526cf330f`，实际 portable `skills/jd-tengfei-diagnosis`。
Git blob 迁入原 cli / inspection / fixed GET transport / 纯汇总和 R01-R12 规则，保留 VENDOR 原来源元数据；没有复制数据库、Web server、公司 SDK、账户数据或另一个 dispatch/task queue。
原 readonly commands、店铺身份（shopId 与 venderId 分开）、抽样/全店分页、请求预算、限流停止、缺指标/partial/not_checked 口径与报告保留；只改商家状态目录、禁止 default、去除重复安装/派单入口和不可对外用的站点按钮。
Node.js 24+ 是原成熟依赖；实际本地 v24.18.0。Python 主派发通过 source provenance 指定 Node CLI，非任意 JS 执行器，无公司请求。
已执行实际 CLI 的单品 dry-run 规划，不调用店铺 API。商家诊断真实权限、指标完整性、跨宿主 Node 运行未验证。
此 portable 原源只提供 R01-R12 官方巡检，不提供完整广告预算/消耗/ROI 输入。广告成熟来源仍须从内部调度继续追踪，不能把巡检等价于广告诊断完成。


## 真实内部调度来源追踪纠正
继续沿内部 registry 的 skill=jd-store-diagnosis / 11128 追踪后，发现实际成熟 Git 源并非前述 Web 应用中的 portable 子目录，而是 `ctzlyj/jd-store-diagnosis-skill` 0.2.0 / `42971c041248bab27f4d627357dcc475f848eb75`（工作区干净）。
该实际来源包含完整 L1 官方巡检、L2 商智/京准通 `make_plans.py -> sz-fetch.js / jzt-run.js`、原数据字典/诊断规则/报告校验及稳赚机制；员工黄金眼 L3 不属本次商家等价范围。
当前包里复制的 portable L1 仍明确记录自己的 bc5a0fb 来源，没有把新增来源标签当成完整复用。下一步应迁入真实成熟 L2 和报告处理，只做商家自有 CDP/Profile、输出目录、宿主兼容适配，不能另写广告分析器。
旧文“广告来源待追踪”已被这份具体源码证据推进为“来源已核对，成熟 L2 迁移待实施”。真实商家网页/广告账户读数尚未执行。


## 真实完整来源已迁入（当前检查点 0.2.7）
不再只是改来源标签：L1 的 cli/inspection/transport/vendor 重新取自实际42971c；L2 make_plans/sz-fetch/jzt-run、实时订单/到手价/稳赚只读探测、原 validate_report、原工作法/数据字典/API参考均按 Git blob 选择性迁入，原来源路径与每文件SHA保留。
未复制员工 GE/EasyBI/cxjzt 或内部发布代码，未复制旧 Windows 启动器按目录强制结束浏览器的路径。宿主必须提供其实际拥有的商家私有CDP/Profile，不猜固定9224。
仅新增薄传输/计划URL/认证字段脱敏边界；原报表API、归因窗口、8维指标、新账号态指标处理指导、数据缺口和结构校验保留，没有新建广告分析器。
已在**安装后的0.2.7包**中使用独立 Chromium + 实际 CDP + Playwright 拦截报表响应，跑通原 jzt-run 的XHR、回包和报告落盘，并验证认证字段不落盘。该fixture没有真实商家/API权限/结论验收。
本地测试还复现并修复了 Windows 清理环境丢失大小写系统目录变量、双层派发丢失商家CDP命名空间和嵌套mature引用被审计错误截短的问题。前述已定位完整L2待迁移的段落是历史记录，当前代码复用与本地传输适配已落实；剩余为真实商家和宿主身份/期间/接口条件验证。
