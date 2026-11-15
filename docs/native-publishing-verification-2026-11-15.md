# 原生全 SKU 新品发布：开发检查点验收

日期：2026-11-15。整体目标继续 active，尚未正式上线/发行。代码提交：`77aef1668d29650589c24d888ae81fa78e7bc2c3`；私有仓库 `ctzlyj/heideng-ops-agent-merchant-skill`，分支 `codex/merchant-foundation`。

## 已实现

- 商家授权类目/三级品牌/实际模板读取；完整 sourceProduct、全部 SKU、规格 alias/mappingId 与原照片上传回执绑定。
- 原生 validation 与 product-applies 使用同一扁平 body，两步各自绑定精确批准；原成功校验回执 SHA、同店、同内容、600 秒内才允许创建。
- 四项评审 P1 先失败再修复：所有 envelope 检查完才 passed；批准前重构安全 HTML；持久创建意图阻断复制目录重复创建并使旧未启动批准失效；最后前检/签名/native HTTP 入口再次检查较早截止时间。
- 新品发布/校验不论载荷大小强制已审核官方源 stdin。官方 TLS helper 的 fallback 也不能第二次启动业务 HTTP，GET 原重试策略保留。
- 仅保存原 applyId/productId；受理、审核、全部 SKU/主图/详情线上生效严格分开。

## 实际测试

- fresh HOME、禁 socket 全套 **256 项通过**。
- ZIP **53 文件（含 manifest）**审核通过，凭据模式/个人路径/未知文件均为 0。
- 包 SHA256：`896cbea1e58514f1f04e86aa2a8da052562c94f3c2d512f9c0587fb1e0b03b7c`。版本 `0.1.0` 仍为非发行开发快照，不把同版快照当正式升级。
- fresh 安装后跨进程全 **1000 SKU** 合成新品闭环：4 次校验、1 次已知创建、1 次另一个明确意图的 unknown；复制/重校验返回原创建任务，unknown 不重放。
- 64 SKU/65 图片槽位无损草案、1000 SKU 价格及素材上传回查回归通过；真实隔离 Pillow 解码，不代表远端像素或商品绑定已验收。
- 从公开通道读取、SHA 校验的真实官方 **0.3.7 源码**，使用合成内存授权与 HTTP，实际运行 parser/signing/request：正常为身份 GET+业务 POST，签名后过期仅有身份 GET、无业务 POST。此测试的二进制 receipt 为未执行 stub，不能冒充真实 OAuth、系统凭据或官方网络写入。
- **真正 GitHub clone** 指定代码提交 → fresh venv/公开 PyPI 测试依赖 → 重建 SHA 一致 → 包审核 → fresh HOME 安装/onboarding → 256 项 suite + 四组 smoke 全通过，克隆工作树干净。不是本地 copy 回测。

## 边界与后续

没有真实商家授权、真实商品/素材写入或模型付费生成；所有 onlineEffective/allSkuOnlineVerified/productImagesOnlineVerified 仍为 false。完整既有商品编辑、图片/详情绑定、原线上全字段验收与正式发行许可仍待完成。去重限于保留了同一本机 state 日志的流程，不声称跨机器或日志丢失后的全局恰好一次。

视频上游本轮核验为 `0.3.0 / 29548089f7b71ac77ddb584caac0966a98df24ab`，provider 未启用；内部只读核验为 `1.5.4 / 13692b759bd52e35c3670cf8fad5330e1bf2b576`，工作树干净，本任务未改动内部版。

机器证据：`native-publishing-verification-2026-11-15.json`、`github-publishing-roundtrip-2026-11-15.json`。仅汇总无凭据验收数据，不提交运行日志、官方源代码、店铺 Profile 或源照片。
