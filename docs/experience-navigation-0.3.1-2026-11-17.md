# 经验导航与开放执行局部优化 — 2026-11-17

## 开始基线与范围

实际工作区 HEAD：0.3.0 / 7804814e836454bbd1a8867d8650dedb426c261e，分支 codex/merchant-mature-reuse；开始时 tracked/untracked 工作区为空。远端默认分支此前已经整合到该提交，推送前重新核对。
只修改当前商家工作区。内部版、个人成熟 Skill 和旧商家工作区不修改；不重建成熟业务，不增加关键词路由、任意 entry、通用业务执行器、重复门禁或定时系统。

## 修改点 → 文件 → 依据 → 保留行为

| 修改点 | 文件（相对本商家工作区） | 依据 | 保留的行为 |
|---|---|---|---|
| 宿主规划、开放组合与按需导航 | SKILL.md、references/experience-navigation.md | 用户已确认总体方向；8个成熟组件缺经验入口 | 原 status/run、登记入口、哈希和来源许可不变 |
| 8类模块经验 | references/experience-*.md | 包内成熟源码/参考说明，逐文标注来源版本 | 原业务计算、店铺核对、平台回执和恢复不变 |
| 规则分层、范围与结果真实性 | references/execution-policy.md | 区分建议/策略/硬限制/授权/恢复/开发 | 同范围不加重复确认；未知结果不换工具重提 |
| 目录外官方工具的隔离用法 | references/merchant-cli-environment.md | 已有 child_environment / OfficialClient / FileLock | 商家 CLI/HOME/Profile 与官方凭据管理不变；只补说明 |
| 历史文档去污染 | references/commands.md、references/workflows.md、开发记录 | 二者是源码历史资料，0.3.0根包24项未包含它们 | 不启用旧builtin，不把历史开发禁令当产品禁止令 |
| 新资料真正分发 | package-files.json、registry.json、README.md、VERSION、heideng_merchant/__init__.py | 资料必须在安装后存在，异包必须区分版本 | 不改 install/distribution 哈希机制，不动 mature/provenance |

## 本轮开发限制（不属于产品运行禁令）

本轮只做静态链接/目录/清单/命令/保护差异及文案场景评审。没有扫码、新授权、真实采集/写入、改价、发消息、付费生成、安装演练或全量成熟测试；不触发 GitHub Actions、不公开仓库、不创建 Release、不通知商家。
此前用户暂停额外开发验证，并未禁止商家未来在真实授权范围内执行业务。产品运行保留当次身份、范围、费用和未知写入保护，而不是开发历史中的“停止业务”指令。

## 静态记录

实施后记录实际资料覆盖、发布清单、受保护文件差异及9项文案场景评审。静态通过只证明文档/清单一致，不证明真实商家、宿主浏览器或外部服务已通过。

### 实际静态结果

- 0.3.1根声明35项，其中新增经验/策略/环境资料11份；实际archive含263项。
- 新资料和入口共68条本地Markdown链接在实际archive内存在，且新资料manifest hash相符。
- 文档Python示例仅AST解析，未执行、未导入、不触发官方取数。
- mature快照/provenance、cli/mature_runtime、身份/授权/费用/未知恢复、安装完整性及CI工作流相对开始HEAD无差异。registry原来源、实际命令、模型/凭据/升级政策保留。
- 旧工作区23份混合实验文件hash与交接保护记录一致；未写内部版/个人Skill。
- 下面9项是文案场景评审，不是模拟执行或商家验收：
  - natural-language-not-a-keyword-route → SKILL.md（相应明确规则存在）。
  - cross-module-new-listing-images-information-score → references/experience-navigation.md（相应明确规则存在）。
  - outside-catalog-official-capability → references/experience-navigation.md（相应明确规则存在）。
  - read-only-without-image-key → SKILL.md（相应明确规则存在）。
  - wrong-shop-identity → references/execution-policy.md（相应明确规则存在）。
  - unknown-write-no-tool-switch-resubmission → references/execution-policy.md（相应明确规则存在）。
  - approved-same-scope-no-duplicate-confirmation → references/execution-policy.md（相应明确规则存在）。
  - no-task-no-business → references/execution-policy.md（相应明确规则存在）。
  - existing-video-not-equivalent-to-ai-generation → references/experience-video.md（相应明确规则存在）。

没有运行成熟测试、安装演练、扫码、真实取数/写入/改价/消息/付费或GitHub Actions；没有关闭任何保护。
本地打包为正常分发生成，不是安装演练；包SHA256：01230532e0a9d735ad48e9ef35739847994c6fc8b62994f356070d6e7948c557。
