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

执行记录：Task1首次RED已复现并修复；独立解码/交接、CLI和新HOME真实公开解码器smoke通过，第一次全套389项隔离测试和9项旧安装回归通过。独立审查的4个问题已分别主流程RED复现并修复，修订代码/完整安装验收仍在进行，最终矩阵/私有GitHub回环记录随后写入验收文档。Task2–3未完成，Task4本轮仅覆盖Task1开发交付，不能据此宣称已上线原生视频链路或整个目标完成。
