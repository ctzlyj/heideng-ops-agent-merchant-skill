# 商家版 LTS4AI 生图（客户端已接入，真实调用未实测）

## 已确定的来源

- provider：`lts4ai`
- `LTS4AI_BASE_URL=https://api.lts4ai.com/v1`
- model：`gpt-image-2.5`，不切换别名/模型/网关。
- 状态：`adapter-ready`；执行接口可用，不再无条件禁用。`liveVerified=false`仅表示没有提交真实付费请求，不表示必须先做一遍业务全量验收才能调用。

## 复用而不是重写

直接复用 ctzlyj/sufy-image2 的 MIT Python 标准库客户端核心，来源 commit、哈希和许可证保存在registry/NOTICE。不依赖个人Skill目录，不复制旧凭据，不安装OpenAI SDK。只增加商家所需的固定来源、确切预算批准和原请求防重投绑定。

成熟客户端的文生图使用 `POST /v1/images/generations`（model/prompt/size/output_format），参考图编辑使用 `POST /v1/images/edits` 的multipart，最多12张参考图、总计15MB，保留参考图顺序。每请求生成1张，多张按用户批准数量逐张提交。可解析原图片字节、JSON base64/URL和SSE图片结果，保存本地原图与SHA256。

用户提供的页面Python示例是`chat.completions.create`及通用聊天提示词，仍作为页面示例记录，不否认其存在；实际接入选择现成客户端的图片专用协议，不把聊天模板作为图片验收依据。2026-11-16只读查询平台公开/api/pricing确认了模型名、每请求1张、submitted_attempt计费说明及图片专用端点目录；不证明真实账号权限或实际请求成功。

## Agent命令（商家不必敲命令）

1. `image-plan --request <非敏感JSON文件>`：形成精确提示词、参考图hash、size、张数、输出目录与费用范围。
2. 展示模型、数量、预估积分与预算上限，取得本次用户批准后`image-approve --plan-id <id> --fingerprint <hash> --confirm`；相同有效范围不重复确认。
3. 只在批准执行时，从受控子进程环境读取商家自己的`LTS4AI_API_KEY`，执行`image-execute --plan-id <id>`。
4. `image-status --plan-id <id>`只读原记录。完成后逐张实际看图核验商品身份/文案/像素质量；文件保存完成不是商品平台上传、绑定、审核或视觉验收。

请求JSON字段：requestId（稳定重试身份）、prompt、size（默认1024x1024）、count（默认1，最多10）、images（可省略）、outputDirectory、budget、quote。quote是当前平台/账户价格证据：unitCost、currency=LTS4AI-points、evidence（平台pricing或api/pricing页）、observedAt（读取时间Unix秒，最多24小时）。估算按请求参数绑定；不是已扣费，也不保证平台最终扣费。预算不足不提交。

## 保留的安全边界

- 不从员工环境/集团Key/个人旧凭据槽取Key，不把Key放进聊天、argv、.env、源码、日志或Git。只有安全设置商家Key和本次付费授权是正常前置，不再以“来源待选”阻断。
- 提交重试为0，不接受重定向，不更换平台；相同原请求完成后不重复生成。
- 模型提交失败/超时可能仍扣费；写入尝试前留记录，未知结果或中途退出保留unknown，不重投，不继续其它张。已保存图片保留。
- 当前未得到可靠的任务查询端点；unknown时由商家在平台查原任务/账单并取回结果，没有证据不能新建请求或用新ID规避unknown。禁止把聊天请求、模型列表或再次提交当任务查询。
- 源码变更仅针对外部模型适配、命令入口和离线请求契约；内部采销版的原业务验收仍保留，不重做其全链路。
