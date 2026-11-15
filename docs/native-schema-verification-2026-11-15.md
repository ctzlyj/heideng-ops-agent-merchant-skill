# 原生全 SKU 编辑模板与价格范围验收 — 2026-11-15

## 本轮交付（不是整体上线完成）
代码commit `f61e6eaa6c0c8365d0d4256ce6fb1d1ce18ea019` 已推送私有 `ctzlyj/heideng-ops-agent-merchant-skill` / `codex/merchant-foundation`。

- product_schema.py/CLI：真实协议的完整编辑模板查询、唯一JSON模板/完整SKU census、前后来源与店铺核验；不猜SkuUUid真实身份映射。
- 主图/长图/逐SKU方图和长图已有槽位的无损本地草案；保持所有SKU、映射字段、详情和未知组件，fresh原回执素材；不生成商品提交任务。
- products.py/verification.py/operations.py：删除旧18000字符guard，1000SKU价变更保持全量三阶段证据；实际transport_for选择stdin。1024字段/256KiB UTF8为本地预算，不是平台上限。
- shared material_contract.py：读回imgSize也必须匹配原已知回执，不因同ID/JFS忽略变化。

## 实际验证

1. 新建Python3.12.10 venv，只有公开测试依赖psutil7.2.2；fresh HOME/禁socket全套 **222项通过**。第一次新venv因漏装tests/requirements.txt而报2个缺psutil错误；按仓库既有开发依赖补齐后完整重跑，不冒充第一次已通过。
2. 分发审核 **49文件（含清单）通过**；包SHA256 `4cce6ab95ddf3bb7c2b0061ce973a1b6d74dbca4040ac703c950143b7c720358`。未包含运行数据、缓存、凭据或个人路径；不是第三方商用权利或真实店铺验收。
3. fresh ZIP安装后跨进程CLI+真实Pillow：64个合成SKU、65槽位完整保留/替换；商品schema POST=0；1000SKU价known/unknown各一次PATCH，待审/线上分离且unknown不重放。素材和旧价格回归也通过。
4. 真的从GitHub重新克隆代码commit，重建SHA一致、fresh HOME安装/onboarding、222项套件和上述schema/价格smoke通过；克隆仍干净。详见github-schema-roundtrip-2026-11-15.json，不拿本地复制目录充当GitHub回测。
5. 一次有界独立review发现3项P2，先RED再修复：数字精度与类型漂移、native key/value（含内嵌JSON）敏感属性、原回执imgSize变化。数字无法精确JSON数值往返时拒绝模板而不舍入；未自建新的通用JSON序列化体系。LongImg/SkuRectangleImage补充测试已通过。

隔离边界是fresh HOME/清理进程环境/测试进程socket禁连；不是操作系统防火墙或真实境外商家网络。Pillow公开依赖在测试命令禁连前准备。官方公开文档按当前policy/SHA读取，不调用需要商家签名且可能刷token的info；无真实OAuth、店铺API、上传绑定、付费模型或消息。

## 状态与后续

版本仍为未发行的0.1.0开发候选；同版不同包不是正式升级，不覆盖旧商家安装或创建正式Release。正式发行需新的版本和权利/权限验收。

`submissionReady=false`、`skuIdentityMappingVerified=false`、`productBound=false`、`remotePixelsVerified=false`都仍有效。模板行数等于SKU census不证明真实映射或必填原值；不能把草案当整版提交或详情已经优化上线。继续完整填充/身份映射、validation明确成功契约、分别批准的整版写入与原回执待审/线上图片验证、新品全SKU上架及其他商家能力；生成模型来源等负责人补充。

视频上游已重新核对0.3.0 / 29548089f7b71ac77ddb584caac0966a98df24ab，不启用内部生图/视频来源。内部基线1.5.4 / 13692b759bd52e35c3670cf8fad5330e1bf2b576 仍干净、未修改。

完整机器证据见native-schema-verification-2026-11-15.json。
