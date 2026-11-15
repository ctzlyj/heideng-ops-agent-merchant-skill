# 短标题持久工作进程：私有研发阶段（2026-11-16）

本阶段不是商家全流程上线验收。独立商家仓库中实现原生持久 worker；不触碰内部版或真实商家账户。正式 C3 审核、完整 health/门户、确认失败子计划、跨版本安全重建、真实商家验收、模型提供方与商业分发许可仍待完成。

## 实现

- 商家 Agent CLI：只读 start、精确 root approve、稳定 execute requestId、原 results/effects/recover、历史 command-status、stop、确认关闭后严格 readonly resume。
- 两把同线程真实锁和安装 archive/files hash 绑定整个生命周期；命令线程只接收/排队，原浏览器 owner 执行。公开 PyPI 依赖、隐藏 Windows 控制台，必要认证浏览器可见；无参数中的凭据。
- 原命令接受→dispatch→独立回执，一次原生尝试和原 uploaded live binding。原上传失去 binding/创建未知不再上传或点击。start 不授予写权限。
- 活动期间持续保留原 native 证据前缀和独立 hash 回执；缺失不能变回 not-started。闭合原资源与 broker 后才保存原 closed/独立 receipt；本机 closed 不代表平台成功，不解除 C3 隔离。
- 活动/未知/孤立 worker 加入写入、安装与回滚门禁；只允许同线程实际 owning witness 处理自己的原件。停止在预检与健康检查后、上传/创建之间和 native dispatch 边界再核对。

## 审查与已完成测量

独立审查确实发现过 1 个 Critical 和 2 个 Important：活动原件丢失可能重传、半写命令误停、预检期间 stop 放行。三项均先复现 RED 再修复；复查 8 个方法通过（26.193 秒），原件删除重投仍保持 upload/create=1/1；暂停接受写入为0/0；预检 stop 为0/0；create 健康检查 stop 为1/0；dispatch 边界 stop 为0/0。没有新 Critical/Important；审查不是全量或真实平台验收。

当前包 SHA256 `323cc61a0145d8c425f2af7620f126e1ac679f8265d56e37816aad78d4f00cd9`，114 个文件含 manifest。包审计通过，未检出个人路径或凭据模式。新 HOME 安装后的默认 managed-install verifier、实际 loopback HTTP、合成 browser/client、owner-thread 原动作、重复 execute 不重投通过；另一个已安装原 C3 effects smoke 通过，但 formalAudit/health/portal/imported/retry 仍未全部成立。

首次本地统一回归实际执行745个测试（1533.484秒），0断言失败、1测试harness错误、0跳过，源码未变；不能写作全量绿色。已发现 Windows 临时 junction 测试被测试 harness 的“只许 Python 子进程”规则过度拒绝；独立精确原测试已通过（1 方法，0.108 秒）。保留首轮真实失败；后续隔离验收只放行该精确本地临时目录 mklink，不放开业务命令或外网。

私有 GitHub 固定代码 commit `dc4590a29e8f2d110849080bf2c913bfb5efc5d9` 的新克隆验收已完成：745 测试全量通过（1392.719 秒），0失败/0错误/0跳过，源码未变；四个新 HOME 安装场景（worker、effects、import、results）通过。本地与新克隆包的113个源文件字节一致，114文件含manifest，archive SHA256一致。首次深嵌套克隆遇到三条已独立复现的Windows MAX_PATH临时工作簿错误，原运行明确停止exit -1，不算通过；固定同一代码的新短路径克隆完整重跑通过（最长对应测试路径223字符），没有跳过或修改业务代码。完整回执见同名 JSON。历史 C1/C2 650+7 和旧 C3 局部70不能充当本次745或新克隆测试。

## 明确限制

元数据最大16MiB，超限拒绝而非截断；前缀/关闭半写入无法证明完整时保持隔离，不自动修复或重启。readonly resume 没有原 root 时不能抓新 source 或创建替代 root。仅处理已审核的原根范围；正式失败行重修仍需原 C2 完整确认失败、当前实际修复需要和新的精确批准。

内部只读仓库 git status 为空，HEAD `13692b759bd52e35c3670cf8fad5330e1bf2b576`；审计基线1.5.4。视频上游审计基线0.3.0 / `29548089f7b71ac77ddb584caac0966a98df24ab`，本阶段未刷新上游，不称最新。没有真实 OAuth/jdo/API/浏览器、店铺写入、付费模型、消息或公开发布。
