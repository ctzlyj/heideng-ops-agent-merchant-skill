# Agent命令约定

所有命令由Agent定位实际安装根目录后执行，路径使用绝对路径并正确引用，商家不复制命令或填写凭据。统一入口scripts/merchant.py默认输出UTF-8 JSON，exit2表示缺条件/阻断，不是成功。

| 命令 | 用途 |
|---|---|
| onboarding / doctor | 中文首次上手、本地状态；doctor --install-cli才下载官方CLI |
| route <自然语言> / catalog | 目录发现，不限制合法目录外能力 |
| official-doc <skillId> | 校验官方协议文档，按实际字段组装请求 |
| shop-connect --profile --shop-name --vender-id | 实时venderinfo核验后绑定明确POP店铺 |
| auth-plan --profile --shop-name --vender-id | 新授权的同会话安全接管计划；目前不是已完成的OAuth签发 |
| inspect-source --source --sheet | 查看CSV/JSON/XLSX列名/范围，不猜数据口径 |
| diagnose --source --output --mapping | 映射真实列名后诊断；部分缺项明确标记 |
| material-audit --source --output | 保留所有SKU，199个SPU一批列缺口 |
| compare --source --specs --output | 精确结构化规格与原生到手价证据的TOP10 |
| prepare-listing --product --source-root --output | 实拍、类目和全部规格转listing-package，无伪造SKU或链接 |
| package-snapshot --snapshot --output | 整理真实采集的SKU顺序、价格证据、素材 |
| attach-video --manifest --video --cover --review | 已有视频真实hash和审核交接，无生成调用 |
| task-plan --profile --operation --verification | 对应官方真实接口的任务计划文件 |
| task-approve --task-id --fingerprint --confirm | 仅用户已明确批准后记录一次精确范围 |
| task-execute / task-status | 执行/只读状态，unknown不能重提 |
| task-readback --task-id --query --expected | 官方GET核对目标状态，不以文件/exit0代替 |
| update-check / update-apply | GitHub发行发现、候选SHA校验和空闲切换 |
| video-source-status / video-source-check | 指定视频repo的来源记录/发现，不启用生成 |
| media-status | 明确图片/视频模型来源待确认 |

XLSX可选openpyxl：由Agent在独立商家运行时从公开来源安装；多可见Sheet须选择真实源Sheet，公式无缓存值不能造结果。不能往全局员工环境安装依赖。

官方CLI调用固定生产环境和官方元数据入口，禁default Profile，禁止CLI的mock-token/print-code/code等不安全OAuth选项。大图超过平台CLI参数限制时，转当前Agent的已授权浏览器上传能力，不截断body、不声称已上传。

## 回查契约

写入计划应在批准前附verification JSON：query（真实官方GET）和expected（原目标商品/SKU、申请/操作关联字段、终态及最终值）。它进入任务fingerprint；task-readback传入的query/expected必须完全匹配原批准范围，不能事后换无关商品来关闭任务。无verification的写入不能被通用回查标记完成，需先核对原回执并补业务原生适配，不能伪造。

反例：调价提交超时后，无关商品正常或目标商品当前价格相同，均不能证明原提交已终止。目标匹配会记录targetStateVerified，但原unknown仍保留，继续阻断重提与新写入；只有能关联原请求的正式平台终态证据才能进一步解除，不提供删除状态/换工具重提的捷径。
