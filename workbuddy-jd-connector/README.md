# 京麦连接卡工程样机

这个本地适配器把京东官方 `jdo-cli` 的授权过程接到 WorkBuddy CLI 连接器约定的 `auth`、`status` 和 `unAuth` 生命周期。它额外提供准备和只读核店命令。开发者可从仓库根目录运行；商家使用时由宿主发起。测试代码通过临时状态目录和合成服务演练同一套命令。

| 阶段 | 开发者命令 | 可核对的结果 |
|---|---|---|
| 准备 | `python -I -B workbuddy-jd-connector/card.py prepare` | 在独立目录准备并校验官方 CLI，创建本次连接专属 Profile。准备应在 `auth` 的十秒限时之前完成。 |
| 交接 | `python -I -B workbuddy-jd-connector/card.py auth` | 标准输出给宿主京东 CLI 当次产生的 HTTPS 授权地址。独立工作进程继续等待京东 CLI 的回调。重复调用会定位原尝试。 |
| 查状态 | `python -I -B workbuddy-jd-connector/card.py status` | 连接就绪时退出码为 0，且保存的官方核店结果与当前 CLI 凭据槽相符。未连接、待处理或归属异常返回非零。 |
| 实时核店 | `python -I -B workbuddy-jd-connector/card.py identity` | 核对当前 Profile 的官方 `venderinfo` 并返回店名、shopId、venderId。已取得 LTS4AI 内测资格的专家通过 `merchant_command` 的 `["card-shop-identity"]` 参数只读消费同一结果。 |
| 断开 | `python -I -B workbuddy-jd-connector/card.py unAuth` | 关闭当前工程连接的本地访问，核对本次官方登出的回执。重复断开可安全收尾。远端会话吊销仍需独立证据，结果保留 `remoteRevocation: unverified`。 |

已知目标商家 ID 时，`prepare` 和 `auth` 可同时使用相同的 `--expect-vender-id`。适配器在 `~/.heideng-wb-jd-card` 中隔离本次连接、官方 CLI 和任务回执。开发测试可在子命令前传 `--state <隔离测试目录>` 与 `--core <本仓库或已安装内核目录>`；专家联调使用约定的默认目录。授权地址仅交给宿主，不进入开发者报告或公开日志。

如果 WorkBuddy 为开发者账号提供了原生 CLI 卡片预览入口，在当前机器的仓库根目录运行 `python workbuddy-jd-connector/local_config.py` 可查看四个生命周期动作及状态匹配规则。`--state <隔离目录>` 可指定本机测试状态。输出含本机路径，只用于本机工程联调。

Windows x64 工程实测使用上述配置和全新的隔离目录。准备阶段下载并校验京东官方 CLI 0.3.7，耗时 2.58 秒。授权命令在 6.14 秒后返回京东地址，前台退出后回调仍在等待。第二次调用在 0.25 秒内取回完全相同的地址。商家尚未同意时状态为 `pending`。本机取消耗时 2.72 秒，监听端口已关闭，重复取消成功。该轮未登录店铺；真实客户端卡片和授权后核店待验。

从仓库根目录运行 `python -B -m unittest tests.test_jd_card_runtime`，覆盖前台启动器结束后的回调、重复连接、店铺身份不符、断开和断开后的只读拒绝。此测试模拟平台调度与京东响应。工程验收、WorkBuddy 真卡片、商家真实授权回读和平台审核应分别记录。0.4.20 专家构建结果为 `readyForSubmission: false`，未提供已上架的连接器 source。

WorkBuddy 的 CLI 连接器发布规范要求支持 macOS 和 Linux，并检查原生连接、登出及远端会话清理。当前京东官方 0.3.7 二进制发行目录提供 Windows x64 和 macOS ARM。正式送审需核实支持平台、断开范围和 WorkBuddy 真实连接器接入。[WorkBuddy 官方 CLI 约定](https://open.workbuddy.cn/docs/connector) · [京东官方 CLI 发行清单](https://mcp-open.jd.com/cli/version-policy.json)
