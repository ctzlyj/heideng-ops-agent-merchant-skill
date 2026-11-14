---
name: heideng-ops-agent-merchant
description: Use when 京东POP商家希望安装黑灯运营智能体，或以自然语言处理店铺连接、商品上新复刻、信息分素材、主图详情、经营广告诊断、素材到手价采集、同规格比价和电商视频交接。不用于员工自营/招商/内网办公。
version: 0.1.0
---

# 黑灯运营智能体商家版

## 首次上手

商家不敲命令、不复制Cookie或授权码、不发送Key到聊天。所有命令由当前Agent用安装目录绝对路径执行。

1. 执行 python "<skill-root>/scripts/merchant.py" onboarding；用一两句话说明已就绪和当前确实需要的动作，不念整份清单。
2. 只有店铺功能需要CLI且未安装时，Agent执行 doctor --install-cli，从京麦官方公开源校验下载，不使用O2/内部SkillHub。
3. 问清当前目标和必要商品/店铺/报表。纯本地分析/采集/准备无需先授权店铺。已有明确目标店的授权只在实时核验后使用；新授权先遵守 references/shop-connection.md。商家只用京麦App扫码、完成平台本人确认；同一上下文衔接官方OAuth。
4. 图片/视频生成来源尚待产品负责人补充。保持awaiting-provider，不弹员工Key窗口、不读取旧模型Key、不静默选择任何付费平台。宿主自身的文本与识图能力可用于理解商品、策划及复核，不额外调用公司网关。

## 开放工具箱，不是目录白名单

先读 registry.json 或用 route 理解用户目标。目录外的合法POP需求也可自主查官方当前文档、组合宿主浏览器/文件工具、编写任务局部脚本。不要把“未登记”说成“不支持”；但缺授权、事实、平台接口或模型来源时要准确指出缺项，不凭名称猜接口，不回退员工系统。

以真实业务完成为目标，不只给建议：核对输入→读取来源→制定本次计划→在已有范围内执行→按官方回执和远端状态验收。不要把准备好的素材/计划/JSON/进程exit0当作上架/绑定成功。

## 可执行入口

- ensure-shop / auth-start / auth-status / auth-observe / auth-cancel / auth-recover / auth-restart：独立店铺连接和同会话扫码OAuth。严格先读 references/shop-connection.md；只保存公开taskId，不导出私有授权页面；失联不重启，原unknown只读恢复。当前Windows新授权已实现但真实商家链路尚未实测，macOS新授权因官方secret argv风险禁用。
- product-list / sku-list / health-list / product-detail / price-plan / price-status：实时原生商品、完整SKU、健康分和受控京东价更新。改价前先读 references/native-products.md，绑定旧价/类目与两阶段验证；待审匹配不是线上生效，unknown不换Profile或接着执行另一写任务。
- diagnose：用户CSV/JSON/XLSX经营广告资料的定量诊断，缺指标标记partial/unavailable，不造黄金眼/EasyBI数据。
- compare：有逐SKU原生上下文价格证据和结构化规格的同规格TOP10。不能把京东价与到手价混用，不依照片就猜规格。
- material-audit：保留所有SKU，按199个SPU拆批，列缺口；优先复用用户已有合规素材，新增图片生成等待来源。
- prepare-listing：真实实拍、用户卖点、真实类目和全部规格→独立listing-package；保留所有SKU，不为未上架产品造京东链接。
- package-snapshot：把宿主在商品原生上下文实际采集的SKU顺序、每SKU到手价和素材整理为包。采集前读 references/collection.md；不把静态搜索价当真实到手价。
- attach-video：用户已有视频/封面进入manifest；真实hash、技术检查、视觉和试听证据齐全才bindable；不调用生成模型。
- official-doc：按官方版本策略SHA读取指定协议。先审阅接口字段/语义；能力新变更时查官方当前metadata，不套旧版参数。
- task-plan / task-approve / task-execute / task-status / task-readback：业务操作的身份、范围、写入授权、去重、unknown与回查。官方CLI调用必须显式非default Profile、vender身份和目标店名/venderId一致。

完整用法见 references/commands.md、references/workflows.md。

## 店铺写入与费用

用户要求设计/安装/诊断并不自动批准上架、改价、绑定、消息或媒体付费。用户明确批准了具体范围时，Agent仅记录一次相同范围批准，不反复提问；变更店铺、商品、模型、数量或预算是新范围。

真实写入必须先形成task-plan并展示目标店、商品、操作和变更内容，获得对应用户批准后task-approve，再task-execute。submitted不是生效；用官方读取或已授权页面核验task-readback。unknown不得重提、换工具重提或删除状态，先查原回执和远端。不能直接绕到原CLI或浏览器执行未批准的写入。

## 不可越过的隔离

只用商家本人合法权限；禁止员工ERP/SSO、黄金眼代理、EasyBI、JoySpace/京ME、公司模型、oxygen-h3和集团账号。内部安装副本、配置、凭据、更新任务和店铺数据不能改动。清单以外任务同样适用。

Key/Token/Cookie/授权码/设备凭据不进聊天、argv、源码、日志、截图或Git。不要读内部Key，即使存在。不要使用原视频11190/jd-main-video-batch；视频工作流源码仓库固定ctzlyj/jd-pop-main-video-skill；生成模型服务来源另待确认，由merchant包装读取经审核版本，不安装未经处理的上游SKILL。

## 安装与更新

入口 install.py；官方依赖由Agent按需要自动补齐，商家不用另找仓库。启动时或显式做更新发现，候选下载/SHA/兼容检查通过且无进行中/unknown任务、无用户修改才切换；失败恢复，禁止静默降级。后台不扫码、不弹窗、不建未经请求的定时任务。

每轮简报已完成、真实证据、未验证部分、输出绝对路径；媒体生成、官方授权、店铺线上生效分别描述，不能编造。
