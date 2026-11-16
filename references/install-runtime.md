# 安装环境准备与宿主目录

由Agent准备，不要求商家自己敲命令、安装包管理器或替换系统Python。先核对实际宿主、平台/架构和可执行程序，不把“文件安装成功”当作“宿主已发现Skill”。

## 宿主目录

默认用户skills目录：Codex `.codex/skills`（如宿主给出CODEX_HOME则按它），Claude `.claude/skills`，JoyCode `.joycode/skills`，universal `.agents/skills`。显式`--skills-dir`优先。JoyCode目录来自本轮内测观察，不代表已证明所有JoyCode版本仅扫描这一目录；宿主若明确提供其它目录，按其实际目录显式安装。

安装后除了文件hash校验，还应让当前宿主重新加载/确认已识别heideng-ops-agent-merchant。未知时报告“文件安装已完成，宿主识别未确认”，不要重复安装到不同目录。旧版误装目录不自动迁移、清空或覆盖；先检查用户修改和准确原目录，再经明确操作处理。

## Python 3.11+ 前置准备

1. 优先复用宿主提供的Python，使用实际完整可执行路径查询版本。已有商家独立运行时也可复用，先核对版本与来源。
2. 系统Python只有3.9时，不更改系统Python，不创建替换全局PATH的配置；安装器不可用不等于Skill源码已安装。
3. 若机器已有可信的uv或其它版本管理器，可由Agent准备当前用户独立Python 3.11+运行时；不要为此强制商家安装Homebrew等全局工具。
4. 无宿主Python/版本管理器时，可评估python-build-standalone公开发行包：来源GitHub仓库astral-sh/python-build-standalone（https://github.com/astral-sh/python-build-standalone）。由Agent从同一可信发行的元数据挑选准确OS/架构的CPython install_only构建，固定release/tag、资产名、版本、SHA256并记录；核对哈希/来源后检查包内路径和链接，安全解压到宿主允许的用户独立runtimes目录。不要猜URL、下载未校验镜像或让商家手工复制命令。
5. 使用下载的Python绝对路径运行安装、onboarding和后续命令；不能安装时使用一个Python、后续又回到旧系统Python。
6. 下载慢时报告运行时准备这一阶段、已完成/未完成项和实际观测耗时；不能用其它环境的6分钟或24MB作为本机预测。失败应报告具体阻塞，保留已校验部分，不反复下载。

这是一份Agent执行指引，目前没有新增跨平台自动Python bootstrap程序；便携运行时的macOS实机安装仍未由本轮验证。不能把指引描述成已经实现一键自动下载。

## 官方CLI与Skill本体分开

`--with-official`是可选组件准备。Skill本体安装成功但官方组件失败：整体保留installed/unchanged/rollback实际状态，officialCli单独返回unavailable、ready及reason，并给warning；只读本体与离线能力仍可使用。包hash错误、路径不安全、用户安装被修改等核心安装错误仍返回blocked。

平台检查只证明本地实现准入，不证明商家授权。当前Windows x64提供官方授权链路；macOS arm64可下载二进制，但当前带凭据执行因上游secret argv风险不开放；其它平台不提供本地官方执行。Intel Mac无官方构建不能以arm64包、明文凭据或猜接口代替。店铺授权前先报告平台限制，不先安装Playwright再失败。

受影响平台可安装Skill、分析报表、整理本地素材、使用独立外部生图；不能因此宣称店铺查询/改价/上架已可执行。需要真实店铺链路时报告该平台缺项，后续统一优化，不自动切换别的平台或复制凭据。


## 开发修复的版本与升级（HD-2026-11-16-006）

可安装的代码、SKILL.md、registry.json、README.md、references或其他包内文件改变时，交付源码必须递增版本号，并同步VERSION、runtime VERSION和元数据。tests/docs下不入包的纯测试记录提交不必单独升版；它们不能弥补先前包内容改变却漏升版的问题。源码检查点与正式Release分开：不通知商家、不发Release，也不免除可安装源码的版本递增要求。

0.1.2承接此前0.1.1的开发修复；已安装0.1.1应直接用核验过的0.1.2候选升级，无需先回滚到0.1.0。已有进行中/unknown任务、用户修改或校验失败仍遵守原门禁，不为升级清除记录。

`same-version-different-artifact`表示同版本内容发生变化，保护不能关闭。安装器的updateAction=obtain-newer-version要求取得版本递增且来源/SHA已核验的候选，rollbackRequired=false不是批准同版本替换。Agent不得自动rollback→install、修改安装收据、删除已安装文件或伪造版本绕过；rollback仅用于明确故障恢复，不是常规升级步骤。完全相同版本及SHA仍返回unchanged。

默认目录和显式skills-dir都会规范化为真实路径；macOS的/var→/private/var属于系统路径别名，测试必须用resolve后的期望值。规范化不放宽安装器对链接目标/不安全父路径的检查。
