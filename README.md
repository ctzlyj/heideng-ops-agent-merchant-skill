# 黑灯运营智能体商家版 0.3.1

本地 WorkBuddy/JoyCode/Codex 等宿主 Agent 理解和规划商家自然语言任务；黑灯提供电商经验导航、独立安装更新、协作边界和成熟执行工具。**经验目录不是能力白名单，status/run只是一个受保护的成熟包装器。**

## 给宿主 Agent 的安装入口

从本仓库源码/解压目录运行：

```text
python install.py --host codex --with-runtime --with-official
```

JoyCode 用 `--host joycode`；WorkBuddy/其他宿主使用其实际 `--skills-dir`。独立安装名与商家状态/Profile不覆盖内部版、个人Skill、商家记忆或任务结果。版本升级和同版本异包/哈希保护保持。

商家直接交办目标。Agent从 [主Skill](SKILL.md) 和 [经验导航](references/experience-navigation.md) 按需加载连接、内容信息分、上新、图文、采集、比价、诊断或视频经验，可跨模块组合、采用宿主工具/官方当前能力和任务局部脚本，不需要先按关键词运行route。

目录外官方CLI也用 [商家隔离环境](references/merchant-cli-environment.md)。原成熟派发仍为 `python scripts/merchant.py run [--entry scripts/已登记入口.py] <capability> -- <原参数>`；不启用旧builtin、不开放任意entry、不删除provenance保护。

## 当前边界

图片保留LTS4AI / gpt-image-2.5与商家自己的Key，不使用公司凭据/额度。独立文本/视觉API未配置时可走成熟宿主生成文件路径；只读任务不要求生图Key。外部AI视频生成仍未配置，已有真实成片交接/上传绑定是不同的成熟能力。

身份、用户本次授权与预算、平台真实限制、未知写入回查和结果真实性不可因开放执行削弱。用户不交办不开展运营，不自建定时系统；同范围已有明确批准不加第二套确认。

## 来源与交付事实

新经验页实际进入package-files和安装manifest；mature受保护源码/许可/来源hash不变。原历史commands/workflows只在源码标记历史，既没有在0.3.0安装包使用，也不为它们恢复旧runtime。商家诊断经验提炼商家已授权京麦/商智/京准通与用户报表，员工EasyBI/黄金眼、固定历史月份不是商家工具/任务参数。

本轮是文档、导航、元数据与分发局部优化，不是新研发业务上线。静态资料/清单检查不等于真实商家授权、导入、写入、外部服务或各宿主实机通过；具体开发范围和未实测事实保存在源码docs/experience-navigation-0.3.1-2026-11-17.md，不作为产品长期禁止令。

不创建Release、不改变仓库可见性、不通知商家。当前默认分支作为统一GitHub分发入口，商家需有相应仓库访问权限。
