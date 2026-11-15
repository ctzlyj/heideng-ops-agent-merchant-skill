# 原生视频交付实施计划（2026-11-15）

目标：商家给出目标即可由一个已安装仓库完成“已有本地视频 → 真实技术检查 → manifest → 原生视频上传/保存 → SKU 主图视频绑定 → 独立回查”。生图/生成视频服务仍等待用户指定，本阶段不选择生成模型、不消费生成额度。自主内联实施；不重复询问已委托的工程决策。

## 边界和已知证据

- 开发仅使用合成商品、Profile、响应和本地合成视频；不得读取或修改真实商家、内部员工配置。
- 官方 API830 有上传地址、保存视频、视频列表、素材42和视频-SKU关系能力；场景 Skill 未覆盖上传，不代表平台没有 API。
- 只读参考观察到 multipart POST 字段 `video_file`，不是 PUT。真实原生输入/输出卡及上传成功响应尚未获验证；不得以参考代码当作真实调用验收。
- 上传URL仅暂存内存，不进入 argv、日志、计划或普通回执；未知写入不因查询到目标值而自动重试/解锁。
- `videoId`（商家素材ID）与 `jdVideoId`（平台ID）不混用；视频列表videoType=1，素材/关系videoType=42。
- status2仅转码成功，4才审核通过；技术检查、视觉/声音确认、提交受理、关联审核、信息分分别报告。

## Task 1：真实视频技术检查与原文件交接

Interfaces:
- `VideoRuntime(state)`：独立公开PyPI解码环境，准备/状态回执，不修改既有浏览器/图片环境。
- `probe_video(state, path) -> dict`：有界原始MP4容器检查，隔离子进程全帧和全音轨解码，时间线/像素/时长限制，检查前后原文件hash一致。
- `probe_video_cover(state, path) -> dict`：真实静态封面图解码，不采用任意字节hash充当封面。
- `attach_video(manifest, video, cover=None, review=None, *, state=None)`：先全部校验，再拷贝相同hash的原始文件；人工technicalPass不作为技术证据。视觉和声音确认须绑定视频hash及封面hash。缺少确认仍可保存为pending，不能bindable。

Steps:
1. RED：伪造ftyp+任意封面+三个true标志必须拒绝且manifest不变（已复现）。
2. RED：hash错误、封面错误、子进程证据错误、源文件变更、超限/损坏/多音轨/外部数据引用拒绝；不可信review不落盘。
3. 实现独立decoder，选择可兼容Python3.11的公开wheel版本并记录license/hash，禁止源码编译/内网源/模型回退。
4. 实现交接与CLI的state/原子修改边界，文档明确技术检查≠视觉验收。
5. GREEN：隔离单测；新HOME实际安装公开依赖、合成带音轨MP4和封面，全解码/截断/坏媒体/原字节不变；归档和旧回归。

## Task 2：上传/保存有界会话

Produces `video-delivery` 原始文件证据、批准范围和不可重放的阶段日志；从Task1消费精确原始hash。

1. RED：错店、错zone/非商家视频type、过期批准、重复分配/传输/保存、丢失回执均拒绝；敏感URL不得出现在argv/文件/错误。
2. 真实zoneType2+当前prod卡校验；批准绑定本地视频、店铺和上传/保存动作，deadline在实际调用前复核。
3. 地址分配→multipart POST→保存视频信息分别持久化阶段状态，保存只用原分配jdVideoId；独立原始回执不可改写。
4. 超时/不明结果保留unknown；只查原ID，不重新上传或另建视频。HTTP2xx不得单独证明成功。
5. 合成整链验收；真实卡/账号不足处保留明确未验证，不切pre。

## Task 3：素材42绑定与回查

1. RED：完整同商品SKU、同店分类、实际标签“产品展示”、只补缺省order1；视频字段/源ID伪造或现有其他视频不得覆盖。
2. 给Operations强制SKU素材guard增加受批准视频会话证明，不能绕过已有图片/文本证明。
3. 原生<=50SKU分块，保留全量视频素材字段及非目标orders，父批准deadline贯穿。
4. 精确videoId查询和完整分页video-sku-rels（稳定total/无重复/无外店）；pending/approved/rejected/unknown分开，不以期望值清除unknown。
5. 合成多SKU/失败恢复回归；新HOME安装整链；真实商家另获本人授权才操作。

## Task 4：私有开发交付

全套隔离回归、既有9安装smokes和新增视频smoke；发行包仅审计目录；私有分支提交/推送；实际GitHub克隆、新HOME安装、相同归档sha和干净clone验证。无正式公开发布、收费或商用许可声明。

## Review focus

- 伪MP4、损坏尾部/坏packet不能仅凭文件头或元数据通过。
- 解码后/拷贝中原视频或封面变更，已有manifest不可被部分覆盖。
- review technicalPass/cover hash及未绑定人工反馈不能提升至技术通过。
- 保存、传输、绑定的unknown不得重复支出/重复写入。
- 视频type1/type42和两个视频ID不可串用；不破坏已存在视频及其他素材。

执行记录：Task1首次RED、独立审查4项原问题的主流程RED/修复/独立窄复查已完成；代码提交5d78ff4bca628a4f92fed024a6ad0ed57b3b7df1。当前393项隔离测试和10项安装/源码边界smoke，以及实际GitHub克隆、新HOME、相同包SHA与干净clone均已验收。中间整店摘要断言失败和公开依赖下载超时及各自重跑保留在验收记录，未宣称前者根因修复。Task2–3未完成，Task4本轮仅覆盖Task1私有开发交付，不能据此宣称已上线原生视频链路或整个目标完成。
# Task2工程裁决与接口（追加）

- 裁决：上传地址分配虽然为GET，按不可重放的有副作用动作处理。准备阶段只查zone/元数据卡，不分配地址；批准后使用冻结店铺上下文、最终deadline检查、禁止任何自动请求重试的官方stdin路径。
- 裁决：签名上传URL只能由官方分配响应进入专用confidential grant；不能由用户配置或generic task提供；不可JSON/pickle序列化，repr不含URL。子进程stdout仅为受控捕获IPC，绝不作为CLI输出/日志。只返回原jdVideoId和非敏感证明字段。
- 裁决：multipart完整发送+HTTP2xx只记录“收到了传输响应”，storageVerified=false；继续保存后以原videoId/jdVideoId查询原素材，分别核对metadata、转码和审核。不把2xx或目标值当成unknown解锁依据，不宣称远端视频原字节验证。
- 裁决：允许官方分配给当前已批准店铺的公开HTTPS目标；禁止用户URL、私人/本机/混合DNS地址、代理、重定向和把JD认证header带给上传端。固定解析的公开IP、原host TLS/SNI及单次连接；绝对deadline贯穿发送/读取。
- Interfaces：`VideoDelivery.prepare(profile,manifest,zone,name=None)`、`approve(sessionId,fingerprint,confirmed=False,ttl_seconds=900)`、`execute(sessionId)`、`status(sessionId,refresh=False)`；`OfficialClient.allocate_video_upload(...)`专用原地址接口；`UploadGrant`单次消费；`transfer_video(grant,path,sha,size,deadline)`有界multipart。
- Session的allocate/transfer/save各阶段调用前持久化，分别保留独立原始非敏感回执；未知阶段只能只读查询原ID并报告，不重新分配/传输/保存，不自动清unknown。即使多阶段已有目标状态也不构造伪原始回执。
- generic task禁止直接调用地址分配或视频写接口；所有同店业务写入也检查未知/未完成video session，不能换入口绕过。素材42绑定proof仍为Task3，不能通过generic素材入口替代。

## Task2复核记录（续接）

- 中间验收：426项隔离测试、12项安装/官方源码边界smoke通过，72个归档文件（含manifest）；仅为修复前中间包，不用于最终交付证明。
- 已复现并修复：完成save后倒退journal并删attempt可二次save；保留或删除journal中的save hash均复现。裁决：独立receipt/anchor与attempt/journal必须完整链接；任何已有阶段证明均在dispatch前阻止重复执行。新增两项RED→GREEN回归。
- 独立窄复核确认原deadline/readback问题及上述save重放已修复，但指出原隔离问题仍有缺口：每条孤立证据必须有完整、合法且一致的shop owner，不能忽略无owner记录或把shop={}视作另店。已用全部四个证据树的合成记录复现；未完成修复和最终重验前不得交付。
- Task3尚未实现；Task2上传/保存验收不能冒充SKU绑定、真实OAuth、真实网络上传或商业许可。
- 上述owner缺口已完成RED→GREEN修复：全部四个证据树的空/缺失owner、default Profile、不完整或非法ID、空店名、混合无owner+另店owner均拒绝；完整一致另店证据仍允许本店继续。37项视频上传/保存专项回归通过，独立最终窄复核与431项最终包矩阵仍待结果；后续验收报告为最终依据。
- 独立最终窄复核已关闭：5项目标回归（含非法owner子例）、5项原残余精确检查、3项_start直接重放guard检查均通过；没有剩余发现。该结论不代替最终431项/12smoke包矩阵或真实平台验收。

## Task3只读审计补充（未实现）

- 官方API830目录已列出`GET.sp-product.v0.sku-material-tags`、`GET.sp-product.v0.media-zones._zoneId.video-sku-rels`及素材批量绑定；场景Skill的“只查视频/无上传接口”表述不能覆盖API830能力。文档中的历史pre建议不采纳，真实动态合同仍须当前prod。
- 只读参考的type42载荷包含`indexImage`、`videoFrom=1`、商家`videoId`、平台`jdVideoId`、title/duration及实际tagId/tagOrder/tagName；标签查询关联商品实际secondCategoryId，“产品展示”须精确匹配原生返回，不能把一级/末级类目ID任意代填。
- 只读参考的关系查询使用`videoType=42`、videoIds及分页；旧代码有total缺失时提早结束、重复SKU覆盖、关系status与relationStatus别名差异等未证明边界，不能整体复制运行。后续需动态卡校验、稳定total、唯一关系、全SKU范围及原ID交叉核对。
- 现有`sku_material_contract`只允许31/32/33/36/1002；42证明不能通过放宽`changes_checked`或generic task绕过，必须接入完整原视频会话、同商品SKU全量清点、父批准/分块和独立审核回查。当前Task2精确元数据证明不包含可直接写入42的完整videoMaterial，需单独读取/校验而非从manifest伪造字段。

- Task2最终验收已完成：431项隔离测试、12项安装/官方源码边界smoke与72文件脱敏归档通过；代码9a1001c42cea8ba628cbfe266bcfe35fa47e4b95已推送既有私有分支。实际GitHub克隆、固定代码、新venv/HOME、相同归档SHA、同431项/12smoke与干净detach clone均通过。Task3仍未实现，完整商家版goal保持active。

## Task3实施裁决（2026-11-15）

复用Python标准库、Operations及原生视频会话，不另建平台；用户已委托剩余工程选择，不重复要求选择技术方案。只做合成测试。

1. 新增`VideoBindingService.prepare/approve/execute/status`及专用type42合同；Operations经显式`videoMaterialInput`分派专用guard，不放松原图片/文本合同，也禁止generic回查提升视频写入。
2. 原视频来源必须是本店已保存、独立回执/anchor/尝试齐全的原Task2会话；重新验证本地视频/封面/manifest和原videoId/jdVideoId。绑定批准与旧上传批准不同，不因旧上传deadline过期强迫重新上传。审核可从2变4，但3/5不可当成可绑定。
3. 全商品详情+完整SKU分页双清点，实际二级类目和当前prod元数据/“产品展示”标签；Agent给出绑定视频hash、商品详情hash及全部SKU的商品身份确认。无确认只读展示，不写入；不要求商家手工写JSON。
4. 只补type42/order1；已有相同完整视频字段可只读复用，其他order1拒绝覆盖。完整保留非目标视频orders和已查询图片/文本内容，并独立读回证明。每chunk<=50SKU，父批准覆盖全量SKU/所有chunk，子批准不能延长父deadline。
5. 视频绑定attempt/receipt/anchor和父批准独立不可覆盖；journal/结果/attempt丢失或倒退不能重复写。未知原提交即使关系/字段已匹配仍保持unknown，并阻断同店后续写入。丢失journal但有遗留证明也不能解除隔离。
6. 关系查询必须稳定total、完整分页、唯一SKU关系、本商品全SKU范围和原两个ID；不将短页、重复覆盖或缺失status当作完成。字段匹配、关联可见、审核pending/approved/rejected、信息分分别报告；绝不推断信息分已刷新。
7. TDD：先复现缺服务及审批/分块/错来源/未知恢复的RED；逐步实现来源、完整范围、类型合同和独立写入证明；再验证篡改/丢失、过期、分页、保留orders、CLI和新HOME原生整链。最终完整隔离套件/归档审计/私有GitHub实际安装往返，不用Task2证据冒充Task3。

### Task3开发验证进展（尚未交付）

- 初组4项RED（缺原生绑定服务）→GREEN，覆盖只读准备/精确父批准、53SKU按50+3、保留已有orders、unknown匹配回查不解锁。
- 后续复现并修复3个有界缺口：商品确认passed=1被当True；缺审核状态被归为pending；submitting journal落盘期间过期仍调用native。现在要求literal True，未知审核单列unknown，在原尝试持久化后、native调用前再次检查deadline；SDK最终deadline仍保留。
- 分页漂移回归首次用了只有50条/total50的第一页，此时不可能观测未来第二页变化；已改为真实需第二页的报告total51→52漂移夹具，证明首块回查失败时不提交第二块，而非为满足错误断言改生产逻辑。
- 13项新增绑定/CLI测试通过；完整隔离套件444项通过。原包72文件已被本轮76文件中间包替代，旧Task2 SHA不用于Task3。中间包SHA7fbfa5b8e3dbba87df826409ed5fe23611625b0e50634d5e786404c68ed49165审计通过，仅为初版，未完成完整安装矩阵或实际GitHub往返。
- 裁决补充：POST只补新增42/order1，不重提已审核其他orders，以免平台重置审核；读回完整视频字段和图片/文本内容并独立报告非目标审核变化，不与内容/顺序变更混同。原生平台真实语义和动态合同仍需真实商家另授权验证，合成夹具不代替真实验收。
- 独立审查与新HOME真实解码/生产multipart/53SKU原生绑定CLI整链smoke进行中。当前修改未提交，不宣称Task3完成。
- 初版新HOME整链smoke已通过：真实公开解码环境、真实本地视频/封面、生产multipart合成连接、53SKU按50+3、保留原素材/顺序、视频与关系/素材审核区分、unknown停在第一块不重提。该初版包已被后续复核修复替代，不能用于最终SHA验证。
- 独立审查4项有效发现均已主流程RED→GREEN：原上传批准缺失、缺关系status推进下一chunk、把非目标审核进度误当内容变化、后来的视频驳回无法只读报告。17项专项回归通过，最终窄复核待返回。原评论中“关系必须含jdVideoId”经证据复核撤回：源视频精确原ID对+完整type42素材相同ID对+关系精确videoId构成组合证明；存在jd字段则拒绝矛盾，不能强加未证明的原生输出字段。
- 四项有效发现的独立窄复核已关闭：13项（4修复、5组合原ID证明、旧上传过期复用及3有界控制）通过；主流程又独立运行同13项通过。新增独立审核域/非目标进度报告回归RED→GREEN，绑定专项18项。最终包449项完整套件已通过，13项安装/官方源边界矩阵最后整链仍在运行；不以初版已安装smoke冒充最终包。

- Task3私有研发交付已通过：代码b43d0556b0e5f93a614151f603a7b54092a5b48c，449项隔离测试、13项安装/官方源码smoke、76文件脱敏归档；实际GitHub克隆固定代码、同SHA、新venv/HOME安装、同449项/13smoke及干净detach clone均通过。没有真实商家或外部付费模型调用，整目标继续active。
- 下一安全修复已用合成unknown传输复现：distribution.busy仅扫generic tasks，独立视频unknown被漏掉；尚未实际触发更新，也尚未修复。后续先覆盖独立视频会话/孤立证据与版本冻结的更新条件，再推进整店已批准写入、驳回修复和短标题。
