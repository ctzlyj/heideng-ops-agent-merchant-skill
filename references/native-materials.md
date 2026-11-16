# 原生图片素材链路

这是图片空间保存和回查，不是商品主图/详情绑定，也不是生图模型调用。用户描述目标，Agent执行命令；不让商家复制Cookie、Key或手工处理base64。

## 读取与规划

- material-zones --profile [--zone-type 1|2]：实时查询本店原生空间，不猜img_编号。
- material-categories/material-images --profile --zone-id [--filters JSON文件] [--page-size/--max-pages/--start-page]：页码方式读取，保存来源哈希，partial和续读segmentComplete不当全量。每页缺paginationData/totalItems时保留partial并要求重新核对该页，短页不能证明完整。此入口不混用会使page失效的cursor过滤；其他合法模式先读当前official-doc再薄适配，不是能力白名单。
- material-detail --profile --zone-id --image-id：真实同店图片详情/引用关系。
- material-upload-plan --profile --image 本地原图 --zone-id 已查询ID --category-id 已查询ID [--name 图片名]：真实Pillow解码原bytes，生成扁平imgBase64+zoneImageDTO。原图不改写，原SHA/尺寸/格式及店铺/类目/官方transport进入fingerprint；准备不上传。
- task-approve --task-id --fingerprint --confirm后task-execute：同一明确范围批准一次，执行前再次核店、空间和分类。多图逐项保留文件/SKU映射和fingerprint，不能因为批次大小裁SKU，也不要对同一已批准范围反复问。
- material-upload-status --task-id --refresh，或task-result-readback --task-id：只按原已知回执imgId解析原批准GET，验证同一JFS路径、名称、分类和解码尺寸/格式。成功仅storageVerified；productBound/remotePixelsVerified仍为false。

未知没有可绑定原imgId时，refresh只报告unknown，不通过模糊名称搜索把现状匹配当原请求终态；也不能换店/换Profile/改名称重传。可以另做合法只读诊断，但不解除原unknown的同店写阻断。历史verified未刷新也不宣称图片当前仍在；复用前重新查询。

## 输入与权限

官方文档的imgBase64<3MB按编码后3,000,000 ASCII bytes严格解释，不能拿原文件3MB作承诺。不静默压缩/改图：需要处理时另做派生文件并重新核SHA/批准。支持原生PNG/JPG/JPEG/GIF/WebP，扩展名须符合实际解码格式；拒坏图、异常像素/帧预算、链接路径和不完整证据。Pillow从当前公开PyPI元数据选择版本与许可，在独立image-runtime安装；不改browser runtime、不复制第三方源码、不读取模型Key。

zoneId/categoryId来自本店原生读取且活动分类匹配；categoryId按官方int64定义，不凭正数猜默认：0或负值只有确实被本店接口返回且status有效时才可选，否则拒绝；不会猜默认空间、分类或把根parentCategoryId=0当任意上传分类。任意公开URL不等于邀约fileUrl能力；该通道需合法伙伴身份适配，当前不使用。分类/格式缺字段时停，不拼旧元数据外层或虚构默认值。

## 通用入口同样受约束

task-plan --result-verification JSON文件可绑定原回执ID，但原生图片POST强制完整本店空间/分类、真实解码及resultVerification，不允许另加宽松静态verification来跳过验收。$result仅指本任务已知回执顶层ID字段，只用于已批准路径参数/同一ID expected；不支持表达式/任意URL或未知请求替代回执。

CLI不输出imgBase64（包括回执JSON文本内的编码以及已知编码回显），返回omitted/encodedBytes/originalSha256标记；真实原请求留在独立本地任务状态。不要把省略后的公开scope重新拼回operation。图片字节不进OS argv（超限在提交前选官方stdin），回显不当成功证据。

## 尚未验证

开发验证为真实图片解码与隔离安装、API file-fake/离线等级，不是商家真实上传。图片空间受理≠远端文件像素身份验收≠商品绑定≠线上生效。绑定要以原生商品申请协议另获范围批准，不能给现有SKU塞假JFS链接；生图已选LTS4AI / gpt-image-2.5，已接通客户端，需商家Key及本次预算批准（references/lts4ai-image.md）。


## Deferred minor

当前本地文件先stat再read_bytes，文件在两步间增长/被替换会在最终尺寸检查前产生超限读取/编码的分配窗口；没有观察到误提交，后续改为限长读取。不要将边下载边增长的文件作为正式输入；这不是解除unknown或重复上传的理由。
