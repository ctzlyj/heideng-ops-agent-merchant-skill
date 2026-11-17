---
name: heideng-ops-agent-merchant
description: 京东 POP 商家在本地 Agent 宿主中用自然语言交办运营任务；提供电商经验导航、独立安装更新与成熟工具。适用于连接店铺、内容信息分、上新复刻实拍、图文优化、采集比价、经营广告诊断及已有视频交接，也支持按任务组合其他商家已授权官方能力。
version: 0.4.0
---

# 黑灯运营智能体商家版

**宿主 Agent 理解任务、规划和组合工具；黑灯提供经验导航、能力安装/更新与协作约定。** 经验目录不是能力白名单，成熟工作流是有适用条件的参考，不是强制执行顺序。商家只描述目标，不要求照例句说口令或先运行关键词 route。

## 开放执行与共同边界

- 通常先复用成熟路径；Agent 可跨模块组合、调整顺序、采用宿主现有工具、读取京麦官方当前 Skill/文档并调用 jdo-cli，或在商家任务目录写局部脚本。目录未命中不代表“不支持”；真实缺权限、工具、资料、服务时只报告具体缺口，其余可行部分继续。
- `status/run`、capability choices、登记 entry 和来源哈希只界定**这个成熟包装器**的范围。不要回落旧 builtin、修改受保护快照或加任意 entry 绕过口；它们不限制整个宿主 Agent 的合法能力。
- 直调官方工具也必须用本商家独立 CLI/环境、正确 Profile 和实时店铺身份；不借用宿主默认 HOME 的员工凭据、不导出 Token。内部用法见 [商家 CLI 环境](references/merchant-cli-environment.md)。
- 同一目标/范围/费用已有明确批准就沿用，不增加黑灯层重复确认；真实目标、覆盖范围、模型/平台、费用或预算变化要说明。写入未知先关联原回执/远端状态，不能换工具重提。完整分类见 [执行策略与硬边界](references/execution-policy.md)。
- 不因安装、连接或读到经营建议就擅自开始业务；用户不交办不运营，不自建定时任务。只读任务无需生图 Key/付费生成准备；按本任务实际需要准备依赖。

## 按问题加载经验

先读 [经验导航](references/experience-navigation.md)，然后只加载相关模块。跨模块任务可同时取用多个模块，不需要另装8份子产品。

| 商家问题 | 按需经验 |
|---|---|
| 连接店铺、已有授权、新授权 | [连接与身份](references/experience-connection.md) |
| 短标题、信息分、素材与透明图 | [商品内容与信息分](references/experience-materials.md) |
| 上新、实拍、链接复刻、矩阵 | [商品上新](references/experience-listing.md) |
| 主图、详情图、SKU图、整店刷新 | [图文优化](references/experience-images.md) |
| 素材、逐SKU到手价和断点采集 | [采集](references/experience-collection.md) |
| 同规格比价、确认后的改价 | [比价与定价](references/experience-comparison.md) |
| 经营与广告诊断 | [商家诊断](references/experience-diagnosis.md) |
| 已有视频交接、上传、绑定 | [视频交接](references/experience-video.md) |

这些问题是导航示例，不是命令词。目录外能力先看官方/宿主实际可用工具与授权，不能因为包装器没有 choices 就拒绝。

## 安装、更新和成熟包装器

由 Agent 从实际源码/解压目录执行 `python install.py --host codex --with-runtime --with-official`；JoyCode 用 `--host joycode`，WorkBuddy/其他宿主用其实际 `--skills-dir`，不猜安装目录。独立名 `heideng-ops-agent-merchant`、状态 `~/.heideng-merchant`；升级不覆盖内部版、个人 Skill、商家记忆、任务结果或运行数据。同版本异包/降级/哈希保护保持，不以手改回执或 rollback→install 当正常更新。

包装器用法：`python scripts/merchant.py status`；`python scripts/merchant.py run [--entry scripts/已登记入口.py] <capability> -- <原成熟参数>`。入口/来源以 `registry.json` 和 `mature/*/provenance.json` 为准。它是复用成熟工具的便捷路径，**不是所有 Agent 工作必经的统一执行器**。

## 模型与当前适用限制

图片保留已选 LTS4AI `https://api.lts4ai.com/v1` / `gpt-image-2.5`，复用 sufy-image2 client；只使用商家自己的 Key，不读公司/个人 Skill 凭据，不回退公司模型/额度。安全 Key 入口按已批准图片任务使用 `python scripts/with_image_key.py run ...`。

独立文本/视觉 API 未配置时，已有成熟宿主生成文件路径可用；宿主无相应能力才报告该缺项，不能假造文本/分析。外部 AI 视频生成未配置与已有视频交接/上传是不同能力：不能冒称已能 AI 出片，也不能据此封锁已有合格视频的交接。

员工自营、内部招商、EasyBI/黄金眼、JoySpace/京ME 不是本商家工具来源。成熟历史验收是复用依据，不等于本次商家适配实测；实际商家授权、导入、写入、付费与各宿主实机仍没有本次实测结论。不要把源码复用、文档补齐或静态核对说成新增业务已上线/真实验收通过。

## 软件更新与版本使用（不是经营调度）

安装0.4.0后常规空闲更新默认开启，24h入口触发/失败退避，用户可说关闭/开启；见 [持续更新](references/continuous-updates.md)。没有交办不会开展经营业务，软件维护不发消息、不登录、不扫码、不调用模型。每个实际任务（包括宿主直调工具/局部脚本/读取资料）先用update usage begin标记唯一任务ID，从返回的packageRoot程序快照使用本任务经验/工具；每步前heartbeat、结束end。当前任务保留loadedVersion，后续任务按宿主实际刷新节点使用diskVersion，不能擅自重启宿主或声称当前聊天立即更新。

旧任务unknown回执和商家私有状态不删；必要时usage标记原回执恢复引用。包内来源pin/哈希、业务授权和费用边界均不因自动更新削弱。旧0.3.1需要由宿主首次升级到有更新组件的版本；私有仓库必须是商家本人的读取权限，不能给维护者Token。
