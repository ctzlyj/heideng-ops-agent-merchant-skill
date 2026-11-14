# 原生 POP 商品与改价开发验收（2026-11-15）

这是商家版独立增量的离线证据，不是内部版历史验收，也不是已上线或真实京麦改价成功。仍为未发行的0.1.0开发候选，最终正式版本需采用独立版本号和审核后发行资产，不以同版本不同内容冒充更新。

## 本次实现

- `products.py`：实时核对POP店、原生商品/SKU/信息分页和详情；保留全部真实SKU范围，明确partial与续读segmentComplete。
- `price_contract.py`与`operations.py`：平铺SkuJdprice PATCH、实际读取后准备旧价/类目证据、批准绑定、执行前全结构重新核验。通用task-plan也不能省略该契约。待审与线上分开；空回执与未知结果不因目标匹配而解锁同店下一次写。
- `verification.py`：精确SKU选择器和Decimal证据，无eval；缺失/重复/外来身份不能验证。
- `official.py`：按官方策略SHA获取参考MD，不限制为七个能力入口；构造argv前拒凭据型业务字段。
- `safety.py`：统一字典和文本的敏感字段覆盖，递归识别scalar内JSON及转义JSON键。普通业务文本不被重写。
- CLI及中文参考可直接规划、批准、执行和查询原任务；README不再要求下载不存在的正式Release。

## 评审与 RED → GREEN

有界独立评审原4项重要问题：通用入口省预检、执行前仅比选中路径、filters秘密进argv、待审错商品解除阻断，均由失败测试复现后修复。复核另发现敏感JSON文本eid/fp/signature残留；本轮先观察失败，再统一规则，覆盖嵌套/转义文本和调用前无参数构造。最后的残留修复为本地回归+全套验收，未额外重开第二轮独立评审。

同版本官方公开Python源按SHA内存静态审计确认：cmd_invoke可调用refresh_auth_context，后者经write_token_bundle进入macos_write_credential，security的-w后跟secret。不能仅禁新授权而开放GET。新增失败回归后，在共同环境入口阻断macOS所有带凭据CLI（包括已有授权查询），且在创建CLI HOME或启动进程前阻断。无macOS实机测试，也不将deprecated源码作为生产transport执行或复制到分发包。

## 实际验收

- Windows Python3.12干净venv、fresh HOME、Python -I完整套件：**150项通过**。测试进程socket connect拦截，不是OS级防火墙。
- 最新ZIP清单36个源文件+1个包manifest，**37个文件审核通过**；个人路径、凭据模式、未知文件匹配为0。只证明自有分发包，不证明官方二进制/第三方运行时全部脱敏。
- ZIP fresh HOME真实安装、真实Python -I跨进程CLI：**通过**。API为文件型fake且命令进程socket禁网络；未批准不写、平铺PATCH、待审20与线上29.9区分、线上20才确认；known写1次，模拟受理后丢响应的unknown意图1次，状态匹配仍不重提、不解锁下一写。
- 包SHA256：`ad6c11cf9700748d41b815e0f62a5725fefee254b2b1e4b08083f06568be0753`。
- 内部1.5.4 / `13692b759bd52e35c3670cf8fad5330e1bf2b576`未改，Git仍干净。指定视频源最后核验0.3.0 / `29548089f7b71ac77ddb584caac0966a98df24ab`，本轮未生成。

## Rulings I made

1. products字段级scopeSet沿用status文档而不是另一文档的分组值，以避免空壳；真实账户还未核验。若错：该账户字段需重新发现，不能声称完整数据或自动写。
2. 续读、页面预算和载荷限制属于本地安全边界，不是平台能力白名单；不能裁掉SKU再假称全部完成。若错：任务会明确partial并需续读。
3. macOS自动刷新也可能secret argv：带凭据执行整体暂停，保留离线能力，不退明文。代价：已有授权商家也暂不能通过该CLI查询，等待合法无secret argv通道。

## 继续项与未实测

尚无真实商家OAuth/商品API/改价、素材上传上新、付费生成、正式Release或远端CI。18KB argv限制仍阻碍真实图片base64和大上新JSON；deprecated公开源不是已获准生产备用。继续审计合法大载荷通道、媒体空间与分类/素材绑定、原生上新、采集和商家经营诊断、发行下载安装。完整目标保持active。
