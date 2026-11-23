# WorkBuddy 本地候选包

先运行商家回归与分发审计，再从仓库根目录选择一条构建命令。

```text
python scripts/build_workbuddy_expert.py --preview --output dist/workbuddy-preview.zip
python scripts/build_workbuddy_expert.py --invite-digests <仓库外的指纹名册.json> --publisher-email <开发者邮箱> --output dist/workbuddy-invite.zip
```

名册是运营方所发各商家高熵专用 Key **原字符串 UTF-8 字节**的 SHA-256 小写十六进制摘要 JSON 数组。由发 Key 的受控后台计算，再将摘要交给构建者。整批商家共用同一个专家包，各人只输入自己的专用 Key。增加新邀请需更新名册并提升发行版本；追加现有 Key 的额度只在 LTS4AI 后台操作。预览包内名册为空，无法运行业务。

专家入口先匹配本批 Key 指纹，再用 Bearer Key 调用 LTS4AI 的只读 `GET /api/usage/token/` 核对额度与到期时间，再以需要完整 TokenAuth 的只读 `GET /v1/models` 核实当前资格。只有两个接口都成功，才允许进入业务。上游明确确认当前资格仍有效、但额度为零或未设上限时，仅暂停新生图。若完整鉴权返回 401/403（被撤销、到期或耗尽等情形可能返回相同错误），交由运营方核实；此时所有业务暂缓。本地不将原始 quota 单位换算成张数。指纹名册只用于本地专家的资格筛选；设备归属、账户分享和上游额度仍由运营方掌握。收到不符合契约的响应、网络断开或凭证无效时，专家提示当前缺口，保留原任务。

在一台没有研发仓权限的干净 WorkBuddy 桌面上验证实际导入、专用 Key 首次输入与重启复用、同店身份、受邀与非受邀 Key、撤销和额度用尽。针对一次已授权商品任务，检查模型名称、额度与 LTS4AI 账单，再升级同一个专家确认原状态。首次启用需宿主可用 Python 3.11+，由内置安装器准备隔离运行时和官方京麦 CLI。专家分发时整体递增版本；与旧 GitHub 安装可并存。本地构建没有上传或上架动作。
