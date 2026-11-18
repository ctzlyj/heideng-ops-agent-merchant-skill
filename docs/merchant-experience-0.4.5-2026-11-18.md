# 黑灯商家版 0.4.5：0.4.4 现场反馈适配记录（2026-11-18）

## 证据范围与实测环境

本轮先读取完整 WorkBuddy 发布数据，而不是只看反馈汇总：21 条主消息、345 次工具调用，原始 `conversation-data.json` 约 2.53MB；并扫描全部工具结果的错误签名。商家原始追问包括默认浏览器、参考图来源、白底审核、透明图抠图顺序和整体不顺畅。

实测基线为 0.4.4 / `8eacc918`，Windows 11、WorkBuddy、宿主 Python 3.13.12、隔离 runtime venv、官方 jdo-cli 0.3.7。实际浏览器为 Edge，系统 https ProgId 为 `MSEdgeHTM`。入口包括 `scripts/merchant.py run connection -- ensure-shop`、`with_image_key.py run materials -- auto-maintain`、原 `reconcile-receipts`、`prepare-cutout` 与 `bind-external-cutouts`。

商家反馈中的平台写入、审核结果和费用仅作为现场证据引用；本轮开发没有扫码、店铺写入、付费生成或真实商家全链路复测。

## 分类结论与处理

| 现场编号 | 分类 | 本轮处理 |
|---|---|---|
| HD-064 Key 输入零反馈 | 产品适配缺陷 | Tk 回退页输出不含 session/CSRF 的本机根地址；浏览器未自动打开也有可见入口，既有 Host/Origin/CSRF 校验保留。 |
| HD-065 已登录仍 waiting_login / cmd_connect NameError | 产品适配缺陷 | 读取实际店名 selector；网页店名仅用于进入官方 OAuth，最终仍由官方 Profile 完整核店；修正显式参数。 |
| HD-066 job null / cancelled 假恢复 | 产品适配缺陷 | 明确 `job_lost`；取消后新建同店 worker，不复活已结束线程。 |
| HD-067 为什么使用 Edge | 产品透明度不足 | 返回实际 `browserChannel` 与选择原因；系统默认和同店复用可区分。显式切换浏览器仍未提供统一商家开关。 |
| HD-068 950×950 与内容相关 400 | 产品预检不足 + 宿主诊断绕行 | 模型请求前归一化参考图为 800×800 JPEG；经验页明确同 SPU 纯商品图 `reference-override`。上游不返回确定原因时不虚构人物/尺寸结论。 |
| HD-069 已有白底导致透明图死结 | 成熟快照分支缺陷 | 透明派生不再错误依赖 `needs_white`；恢复原同 SPU 白底并本地派生，不新增模型请求。 |
| HD-070 单 SPU 外部抠图 target=None | 成熟快照参数缺陷 | 向冻结计划透传 `target_spu_id`，不扩大全店范围。 |
| HD-071 单 SPU 与全店文案差集/乱码 | 宿主输入口径 + 局部体验 | 本轮不静默过滤其它 SKU 文案；文档要求提供对应子集 agent-text 文件。仍需后续真实内测决定是否提供安全差集投影。 |
| HD-072 未知写入只有英文提示 | 产品适配缺陷 | 返回中文说明和原任务 `reconcile-receipts` 命令，禁止盲目重提。 |
| HD-073 单 SPU 新目录冲突 | 文档/宿主使用问题 | 明确在原全店任务目录用 `--target-spu-id`，不另建底表任务。 |
| HD-074 全店/槽位/短标题口径 | 文档与宿主理解问题 | 全店新计划使用 `--include-full-score`；最终以冻结 SPU/SKU 差集为准，不以 issue 数当付费数。 |
| HD-075 对账显示 0/0 | 产品摘要投影缺陷 | 对账按已回收、审核中、未决回执显示，不再伪装成通用商品进度。 |
| HD-076 宿主 Python 缺 Playwright | 运行时入口问题 | 保留 runtime 隔离与安装预检；标准在线安装默认准备依赖，未借个人/公司环境。 |
| HD-077 update / controller 帮助入口 | 历史适配问题 | 控制器帮助与契约不再依赖状态目录；update runtime 既有回归继续通过。 |
| HD-078 产地 areaCascade 字典 | 平台能力缺项 | 不猜内部接口；没有已核验官方地区字典入口，仍需合法选项证据和商家确认。 |

## 神经抠图安装优化

复用现有 `requirements-cutout.txt` 和 `prepare-cutout --download`，不新建抠图业务。标准在线安装默认准备 `rembg[cpu]==2.0.85` 与固定 SHA 的 `birefnet-general-lite`（首次约 214MiB）。离线或失败独立 deferred，不影响其他能力；本轮测试没有真实下载。

常规新增透明图仍用本地快速派生。驳回透明修复保持京麦批量抠图优先、神经修复兜底；神经失败不静默退回旧泛洪，不调用付费生图。

## 宿主误用与平台边界

- 正常场景/卖点生图使用同 SPU 商品参考图，不需要 approved 白底；`No approved white source` 是京麦批量抠图兜底提示。宿主此前把兜底当主路径规则，不是修改生图提示词的理由。
- 宿主误杀进程、注入生成清单/删 state 等绕法未固化进产品。未知结果继续以原回执对账，禁止重放。
- 平台审核中、`material count mismatch`、权限/风控不是“工具已成功”。仍需按原任务回读或本人处理。

## 本轮离线验证

- 新增回归均先观察预期失败，再最小修复后通过。
- `python tests/run_usability_offline.py`：150/150 通过（0.4.4 基线为 133 项）。
- 连接/单流程、Key、安装、runtime、素材、merchant experience 局部测试均通过。
- 未执行真实扫码、京麦写入、短标题导入、素材上传绑定或付费生图；这些不能由 mock 数量替代。

固定包为 `updates/artifacts/heideng-ops-agent-merchant-0.4.5-3f1a153d8384.zip`，SHA256 `3f1a153d83848f16f580a32e75a3ab33249ff95020f1f68842ab2334008fe73e`，签名索引序号 6。`tests/test_release_consistency.py` 已通过，最终源码重建与固定 ZIP 的逐文件清单及 SHA256 一致。旧商家目录 23 个保护文件哈希保持 0 缺失、0 不匹配；生图提示词相关 diff 为 0 行。

仍需真实商家内测验证：新店零宿主循环连接、老店复用、同店中断恢复、多店隔离、Key 可见输入、参考图恢复、透明图/驳回修复及平台审核回读。
