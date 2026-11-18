# 0.4.4 商家现场反馈修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 0.4.4 WorkBuddy 实测中阻断新店连接、Key 输入和单商品素材收尾的适配缺陷，并纠正参考图与恢复指引。

**Architecture:** 保留现有宿主规划、成熟连接器和 POP 业务链，只在身份交接、交互投影及既有分支条件做局部修改。网页登录只作为发起官方 OAuth 的前置，最终店铺身份仍由官方 Profile 实时核验；Key 页面仅输出不含会话 Token 的 loopback 根地址。

**Tech Stack:** Python 3、unittest、现有 Playwright 控制器、jdo-cli 适配、openpyxl。

**Spec:** 2026-11-18 商家 0.4.4 完整 WorkBuddy 对话及工具结果；项目 AGENTS.md 与本轮用户约束。

## Global Constraints

- 不修改 `_shared_image_rules`、`image_prompt` 或任何生图提示词。
- 不执行真实扫码、店铺写入、付费生成，不读取商家或员工凭据。
- 不新增调度引擎、授权系统或第二套审批；同店默认恢复，多店 Profile 隔离。
- 修改 mature 快照后更新 provenance 商家哈希并保留上游来源/commit。
- 最终递增 VERSION，经 `scripts/publish_stable.py` 发布并通过 `tests/test_release_consistency.py`。

## Review Focus

- 网页只有店名、没有 venderId：允许进入官方 OAuth，但最终官方核店仍必须同时匹配目标店名和 venderId。
- Key 页面 URL：不得输出 session/csrf、Key、Cookie 或 Token；宿主必须在浏览器未打开时看到安全 loopback 根地址。
- 平台已有白底而透明图缺失：只恢复同 SPU 已确认白底并本地派生，不重新调用生图模型。
- 单 SPU 外部抠图：冻结计划 target 与 CLI target 必须一致，不能扩大到全店。
- 连接任务丢失/取消：明确报丢或新建同店任务，不假装仍在等待或原地复活已结束线程。

---

### Task 1: Key 输入与无环境裸错误

**Files:**
- Modify: `heideng_merchant/merchant_key_ui.py`
- Modify: `heideng_merchant/host_connection_controller.py`
- Test: `tests/test_merchant_key_input.py`, `tests/test_connection_single_flow.py`

**Interfaces:**
- Produces: `_prompt_local_page()` 在 stdout 输出 `awaiting_key_input` 事件及无查询参数的 `keyInputUrl`；控制器 `--help` / `--describe-contract` 不依赖状态目录。

- [x] 写浏览器打开失败仍输出安全 URL、URL 不含 session Token 的失败测试；写控制器无 `HEIDENG_MERCHANT_HOME` 的帮助/契约测试。
- [x] 运行相关测试并确认因缺少提示和提前构造控制器而失败。
- [x] 最小实现 loopback 根页面、结构化提示和静态帮助/契约入口。
- [x] 运行相关测试确认通过，且既有表单 Host/Origin/CSRF 校验保留。

### Task 1A: 安装期神经抠图准备

**Files:**
- Modify: `install.py`, `heideng_merchant/runtime_dependencies.py`, `SKILL.md`, `README.md`
- Test: `tests/test_install_entry.py`, `tests/test_runtime_dependencies.py`

- [x] 写标准在线安装默认包含 cutout 依赖并调用既有 Lite 权重准备入口的失败测试。
- [x] 最小复用 `prepare_runtime(optional="cutout")` 与 `prepare-cutout --download`，离线/失败独立 deferred。
- [x] 验证不进行真实下载、店铺写入或付费调用；文档区分 Python 依赖与约 214MiB 权重。

### Task 2: 新店连接与恢复

**Files:**
- Modify: `heideng_merchant/host_connection_controller.py`
- Modify: `mature/connection/app/browser_auth.py`
- Modify: `mature/connection/app/browser_adapters.py`
- Modify: `mature/connection/app/server.py`
- Modify: `mature/connection/scripts/linker.py`
- Test: `tests/test_connection_experience.py`, `tests/test_connection_single_flow.py`, `tests/test_merchant_experience.py`

**Interfaces:**
- Produces: 网页店名匹配可在缺 venderId 时衔接 OAuth；官方 `_matches` 仍要求完整身份；`job_lost` 明示服务任务丢失；取消任务可同店新建；返回实际 `browserChannel`。

- [x] 写 `#shop-base-name` 身份、店名单独进入 OAuth、最终官方完整核店、`cmd_connect` 变量、job null、cancelled resume 和通道回显测试。
- [x] 运行并确认各项按现场原因失败。
- [x] 最小修改现有身份判断与 Manager/Linker 分支，不引入持久任务系统。
- [x] 运行连接局部测试并确认通过。

### Task 3: 素材参考图与单 SPU 收尾

**Files:**
- Modify: `mature/materials/scripts/jd_material_agent.py`
- Modify: `references/experience-materials.md`
- Test: `tests/test_mature_materials.py`

**Interfaces:**
- Produces: `needs_transparent` 独立于 `needs_white` 派生；`bind-external-cutouts` 透传 `target_spu_id`；未知写入返回中文恢复说明和原任务 `reconcile-receipts` 命令。

- [x] 写已有上传白底但无需白底新生成时仍派生透明图的失败测试；写单 SPU target 透传和未知写入恢复命令测试。
- [x] 运行并确认分别因联合条件、写死 None 和英文无命令提示失败。
- [x] 修改既有条件、参数和错误投影；不改任何提示词，不增加付费请求。
- [x] 更新经验页：主路径参考图不是 approved 白底，纯商品图 override 在原任务恢复；全店计划与真实缺口口径一致。
- [x] 运行素材局部测试并确认通过。

### Task 4: 证据记录、完整验证与 0.4.5 固定包

**Files:**
- Create: `docs/merchant-experience-0.4.5-2026-11-18.md`
- Modify: `references/experience-connection.md`, `mature/*/provenance.json`, `VERSION`, 发布生成文件

- [ ] 记录实测环境、真实缺陷/宿主误用/平台限制分类，以及未做的真实商家验收。
- [ ] 运行 `tests/run_usability_offline.py` 和本次局部测试，确认无回归。
- [ ] 更新 provenance 商家哈希并确认受保护旧目录 23 个哈希未变。
- [ ] 使用 `scripts/publish_stable.py` 生成 0.4.5 签名固定包，运行 `tests/test_release_consistency.py`。
- [ ] 检查最终 diff、包清单和工作区，仅提交/推送本轮差异；不创建 Release、不公开仓库、不通知商家。
