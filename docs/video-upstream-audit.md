# 指定视频上游审计

日期：2026-11-15；源码只读、未修改上游。

## 基线

来源 ctzlyj/jd-pop-main-video-skill；默认分支 main；HEAD 29548089f7b71ac77ddb584caac0966a98df24ab；VERSION 0.3.0；该提交日期2026-11-03。仓库 private，未见 LICENSE。

已阅读 SKILL、VERSION、requirements、providers、pricing、config、item_video、video_job、costs、identity、ai_ad、qc_video、voiceover、align_subs、audio_track 以及测试防联网逻辑。requirements 为 requests/Pillow/imageio-ffmpeg/pypinyin/pytest/edge-tts/numpy；只有实际依赖审计后安装到独立运行时，不借用员工环境。

## 路由与默认值

- chat 默认 ark-seed-2.1-lite，image 默认 ark-seedream-5.0-flash；均为上游历史预设，不是用户选择，也不证明当前账户可用。
- video 必须显式选择，无默认值。Ark 系列预设非trial；Yeta试用；oxygen-h3 有 internal_exploration=True，历史探索例外不能传给商家。
- LibTV MCP为可选路线。其账号/模型/价格/准入要单独查，不能要求集团账户。
- 上游 pricing 内价格/汇率是2026-10/11历史快照；第一阶段不把这些直接作为当前真实报价。官方文档抓取/账户验证未完成，实际选择和预算待授权。

## 保留的成熟约束

真实商品选中款与包装身份；前台可证明卖点；unsupported/ease/platform claims检查；首尾帧默认各一次；不合格默认不重生；引用图/视频身份/QC/叠字检查；费用先预留；video提交前状态落盘，有 task ID 只查询；生成不上传不绑定。

## 缺口及证据

| 缺口 | 源码依据/本轮验证 | 商家处理 |
|---|---|---|
| 内部体验入口仍可执行 | providers.VIDEO_PRESETS/make_video 包含 oxygen-h3；测试特意允许 oxygen_h3.py | 商家配置/入口/恢复/transport共同拒绝，不暴露 raw SKILL，不改上游 |
| 错误可能泄露回显 | providers.py:81,99 与 video_job 存原始 response/exception文本；mock假凭据回显检查为True | 统一异常类型/安全字段；请求/响应/日志先脱敏，不直接传原文 |
| 文本/图像unknown仍可重调 | Runtime 未绑定持久操作指纹；同一mock文本超时后再次调用，POST=2、unresolved=2 | 各付费原语都有持久状态/指纹和重复阻断，不只保护video |
| 预算检查不原子 | Ledger.reserve读取累计后_append无互斥；barrier并发mock，cap1.0、两个0.6都预留、合计1.2 | 原子账本/次数预留、跨进程互斥；保留unknown金额 |
| 共享全局runtime | providers.set_current为模块全局，QC/身份共用；流程可能并发 | 每任务独立进程/已审核client，不在线跨任务替换全局变量 |
| 恢复未绑定原输入 | video_job状态未校验prompt/图片/模型/版本指纹；上游main恢复会先走其他步骤 | 商家只读恢复命令直查原 task，旧输入/版本匹配，否则停 |
| HTTP失败释放过于宽泛 | video_job对任意HTTPError按0/void处理 | 只按平台合同确认未受理；5xx/异常结果保留unknown |
| 本地配音回退失败 | audio_track.tts_wav导入 config.TTS_VOICE，config无该字段；离线直接调用复现ImportError | 先验证并包装本机能力；不静默换收费TTS，未修前不声称完整离线配音 |
| 预上架包不兼容 | main:75 必须resolve_link，再读取真实网页/sku图；无listing-package输入 | 商家SourceContext与组合器复用上游模块，不伪造URL/SKU |
| manifest协议缺失 | 上游输出report/视频，不发布manifest.video；原mover gate调用11190 verify-handoff | 独立交接schema/QC/试听/hash，缺复核bindable=false |
| 端点拦截不足以全局隔离 | guard_external是字符串黑名单；视频query/下载与外部TTS另有路径 | 统一外部transport、redirect/DNS/下载鉴权检查，环境最小化 |

## 本轮实际测试

上游 pytest 全套：120 passed in 1.14s，exit0。测试子进程移除所有非允许环境，临时HOME，禁第三方pytest插件，socket连接与requests都阻断，关闭字节码/pytest缓存。没有Key/费用/商家写入。

附加探针（没有改源码、只在审计进程用mock）：
- 并发预算：cap1.0，接受2个0.6预留，持久预留1.2；为隔离预算问题，探针将append写串行化，仍可复现。
- unknown文本重调用：提交2次，未解决预留2个。
- 错误脱敏：合成服务回显假凭据，原异常包含该假值=True；没有输出假值正文，更没有使用真实凭据。
- 本地TTS回退：ImportError，missing TTS_VOICE=True；没有生成音频。

这120项是上游回归，不是商家版安全测试完成，更不是实际外部生成/视频质量验收。所有缺口尚未修复，只纳入商家设计和后续回归。

## 更新原则

上游持续跟随，但每任务锁定实际commit/文件SHA用于复现。发现新版本后先候选下载/校验/审核/契约回归，idle且无unknown、本地改动时才激活；不任务中换代码，不覆盖修改，不静默降级。private/许可未明时不对外打包。
