# B2 短标题原生执行 API 私有研发验收（2026-11-16）

## 结论与范围

代码 `02a909d126c7546e3efadab64b6379092890684e` 已通过本地 **601 项 + 6 个安装后 smoke**，并从实际私有 GitHub 仓库全新克隆同一 commit，在全新 venv/HOME 安装后通过同样 **601 项 + 6 smoke**。安装包 **98 个文件（97 个受 manifest 校验的源文件 + manifest）**，SHA256 `038f90688e7840b380f24c7b344edfafaa6ee6c7cc2566c42e181c6fb5b53ecc`。这不是公共发布、真实平台链路验收或商家自动导入完整上线。

B2 提供同进程 Agent 可调用的原生 upload/create/recover API，以及 CLI plan/approve/status/rows。所有已关联任务仍是 `submitted-awaiting-verification`；`imported`、实际短标题/逐行结果/health 验证为 false。**C 完整回读和持久 owned worker/merchant execute CLI 仍是目标必须部分**，不交导表/人工上传作为完成替代。

## 实際验证

- 本地全套：601 tests，913.018 秒，exit 0；569 基线 + 32 持久新方法（23 import manager + 5 browser + 4 boundaries）。六个 installed smoke 分别为 import API、B1 browser source、A1/A2 plan、material repair、material execution、native update gate。
- GitHub：真实私有 clone → detach 同代码 → fresh venv/public PyPI 测试依赖 → identical bundle → package audit → fresh HOME install/onboarding → full 601 → 同六个 smoke → clean clone。所有阶段按原 handle/同一 workdir执行；没有凭 elapsed time重复提交全套。
- 包审查：personalPaths/credentialPatterns/unknownFiles 均 0；只覆盖审查安装包，不证明第三方 runtime 或真实店铺可用性。
- 独立 bounded review：原两项 Important 均修正，8 个合成场景通过；19 个记录文件哈希核对无变化。清晰限定为 ambiguity/root-wide-instance/live-approval，不能冒充全平台或全回读审查。

## 修正及失败证据说明

1. 矛盾/坏 actual ID 不再与 omitted ID混为一谈；ACK明确 instanceEvidence，矛盾状态不自动 anchor。实际 ID在整个 root唯一，独立 reader也拒绝复用。
2. 真正 5000+1 重复实例 RED后修正；首个自有 fixture过早隐藏页面的无效尝试保留但不作为安全依据。
3. 浏览器 Response.finished 与解码 body界限分离于压缩 Content-Length；responseSha256仅browser body，不声称 wire bytes。
4. 合成模板因 ZIP 2秒时间粒度而hash漂移，确认 XML相同且仅日期不同，固定 synthetic date 2000-01-01；没有放宽生产模板hash。
5. 新health审计的自争 install.lock改为复用真正 held同线程同路径 witness；inline approval保留 original open owner，cleanup未知不放锁、不移除live reference。
6. installed smoke最初 synthetic clock与CLI实际 clock不一致，只注入一致 manager，业务断言未减弱。

## 安全及未验证项

测试身份、店铺、浏览器 factory/响应、模板、批准均 synthetic。真实 OAuth、authenticated jdo info、商家网页/API/写入、付费模型、消息均未执行。签名 URL及JSON/DOM原文不保存到状态/报告；不借员工 ERP/SSO/Key/Profile或内部 SkillHub，不操作工作浏览器。

内部只读基线仍 **1.5.4 / 13692b759bd52e35c3670cf8fad5330e1bf2b576**，当前 Git状态干净。视频上游记录仍为**已审计 0.3.0 / 29548089f7b71ac77ddb584caac0966a98df24ab**，不称latest。

真正实时模板/schema/type/pagination/结果文件和original title来源、其他操作员并发修改的服务端保障、类目与规模、分发/收费许可仍需各自验收。生图/视频服务来源待用户选择；总体 goal仍 active。

## 复现

先 checkout代码 commit，准备 fresh venv并从public PyPI安装 tests/requirements.txt。全量 `python -I -B tests/run_offline.py`；六个 tests/smoke_*.py（只执行上述六个）。`scripts/build_release.py` 和 `scripts/audit_release.py` 校验包；offline install指定包及精确SHA后由installed scripts/merchant.py运行 onboarding。具体 stage receipt和区分范围见同名JSON。
