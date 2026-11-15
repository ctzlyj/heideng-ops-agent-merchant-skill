# 本地视频技术检查和交接

商家仍只描述目标，不需要手写命令或JSON。以下接口由Agent执行；不会生成媒体、调用模型或写店铺。

## Agent流程

1. 确认已有视频属于本次商品；先 `attach-video --manifest … --video … --cover …`，独立检查原MP4和封面。首次保存为pending，不是店铺绑定。
2. 实际查看全片、检查商品/文字/服装等一致性，并播放音轨或让商家试听。技术解码不是视觉验收，也不识别台词或证明商品身份。没有视觉能力或无法试听时继续pending，不填确认值。
3. 从返回 `video` 获取视频sha256、coverSha256、listingFingerprint。视觉和声音已确实确认后，Agent在本地写review：同名三个hash，以及visualPass/voiceConfirmed布尔值。可保留旧technicalPass字段但它不参与技术判定。
4. 同一 `attach-video` 带 `--review` 保存确认。更换封面、视频或商品manifest需重新确认，旧hash不能沿用。视频/封面原字节不转码、不改图。
5. 上传/绑定之前运行 `video-preflight --manifest …`：重新解码并核对原文件、封面、商品上下文和确认。`locally-reviewed`/bindable仅代表本地就绪，不是原生视频上传/保存、SKU绑定或审核成功。本轮原生上传与素材42绑定尚未接入，不能借通用task-plan绕过素材证明guard。

工具：`video-runtime-status`离线检查；`video-runtime-prepare`仅安装公开解码依赖；`probe-video --video …`报告技术证据；`attach-video`进入manifest；`video-preflight`独立复查。

## 检查边界

- 独立商家state的PyAV环境，公开PyPI av16.1.0二进制wheel，版本固定且pip核验SHA256。安装后记录完整site-packages文件hash清单及清单hash，导入av之前重新核对，修改/新增/删除依赖文件均使就绪检查失败。旧版未记录完整性证明的runtime不会静默复用/覆盖，需保留状态并由Agent审查后迁移。选此版本是为了兼容项目Python>=3.11；并非声称它是最新版本。不使用系统FFmpeg、个人Skill、Oxygen、公司网关或生成模型。无匹配wheel时阻塞，不编译源码/切内部源。
- 封面复用独立Pillow环境；真实解码静态PNG/JPEG/WEBP，小于3MB，非任意字节hash。运行时安装在商家自身state，发行ZIP不打包第三方wheel。
- 原始非分片、自包含MP4，1个H.264视频轨，可无声音或有1个AAC音轨；外部数据引用、多轨和未经支持的codec拒绝。当前保守配置不等同覆盖京东所有可接受格式。
- 最大500MiB、180秒、4096×4096、120fps、21600视频帧，累计最多120亿像素；音轨8–96kHz、1–2声道、1800万samples。单次解码子进程120秒墙钟限制，单codec线程。依赖/进程隔离不是针对恶意原生解码器漏洞的安全沙箱。
- 全帧/全音轨实际解码；在各真实codec context显式开启严格错误检测；坏packet/frame、可恢复但有解码错误的数据、时间线不连续、非有限浮点音频、声明与解码数量/时长不符拒绝。AAC尾部最多100ms容忍、音视频尾部差最多250ms，不补帧或静音修复。
- 前后hash和有界拷贝核对，先完整验证再保存；全长内容hash命名，原子创建不覆盖已有不同文件；manifest锁、同一次读取解析/保留的原始快照和变更检测保护原配置。preflight完成两个探测后再次有界核对视频与封面，防止检查封面期间视频被替换。Windows文件系统不支持同盘硬链接时安全阻塞，不降级覆盖写。
- 长Windows路径导致venv/pip失败时保持not-prepared，不改注册表、不动内部环境。商家目录过长可迁移到较短的自有state路径后重试；本次新HOME实测使用系统临时目录。

## 许可和验证

PyAV元数据和wheel中的LICENSE.txt标为BSD-3-Clause；该标记不能代替wheel内FFmpeg/编码器等依赖的各自许可审计。运行时来源、版本、可用wheel SHA与声明许可记入本地回执。公开/商业分发仍需单独审查，不将PyAV许可推广为公司成果或整个项目商用授权。

仅合成媒体和隔离测试；没有真实商家登录/上传/绑定，没有外部生成、付费调用或真实商业视频视觉验收。`tests/smoke_video_handoff.py`针对新HOME安装后实际运行的代码验证，不用mock解码器代替全帧检查。
