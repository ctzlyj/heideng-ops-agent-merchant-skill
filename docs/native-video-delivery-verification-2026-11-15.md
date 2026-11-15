# 原生已有视频上传/保存验收（2026-11-15）

## 本轮完成范围

Task2：原始本地视频交接证明 → 当前店铺视频zone/原生元数据合同 → 精确父批准 → 官方源stdin分配 → 有界multipart POST（video_file）→ 原jdVideoId保存 → 精确元数据读回。只完成已有视频的上传/保存适配，**不生成视频，不进行SKU素材42绑定**。

- 原始文件先hash匹配并制作私有有界快照；连接期间源文件变化不能换掉上传内容。
- 分配虽为GET，按有副作用不可重放动作；保存和分配都使用冻结店铺/最终deadline/禁止SDK业务重试的审计路径。
- 签名URL只经受控捕获IPC进入单次非序列化grant，不进入业务计划、普通回执、日志或argv；无认证header/代理/重定向，公开单播DNS固定、原host TLS/SNI验证。
- allocate/renew/transfer/save尝试、原回执、anchor与独立父批准交叉核对。未知结果保留隔离，只读原ID不解锁或重放；已有阶段证明即使journal倒退或attempt丢失也不能二次提交。
- 每条孤立记录都必须有完整合法且一致的店铺owner；空owner或混合ownerless/另店owner不能绕过。完整一致另店证据不牵连本店。
- HTTP2xx只证明收到传输响应。转码status2与审核status4分开；无refresh仅历史状态，新读回找不到原ID降为saved，不能假称ready。远端原始hash/像素和封面一致性仍未证明。

## 实际本地验收

- **431项隔离测试、12项安装/官方源码边界smoke全部通过**；其中视频专项37项。新HOME真实安装公开解码依赖，使用合成H264/AAC视频/静态封面全解码，执行生产multipart代码但连接/DNS均合成。
- 归档：0.1.0-unreleased，72文件（含manifest）；SHA256 `b9348f114c48f4bc62e8584c7956b1b76cd4a02dbbdfe1bb59649bbb102f73ea`。零个人路径、凭据模式或未知分发文件；仅证明本项目受审计归档。
- 官方0.3.7公开源码SHA `abcc6fe5a354d14c4a9b99a221d0b682759d77e8200fc3922f0c1ce32e86a0b2`；实际parser/signing，合成认证、最终HTTP替身和socket阻断。4例涵盖分配/保存成功及签名后deadline过期；没有真实OAuth或平台写入。
- 独立审查及后续窄复核：原3项问题及追加save重放、owner残余分别RED→GREEN。最终窄复核5项回归、5项既往残余检查、3项直接阶段guard检查通过，发现项均已关闭。实际GitHub往返记录随后写入本报告JSON，不能以本地通过冒充远端交付。

## 中间失败与重验

426项/12smoke中间包后发现追加save重放；428项隔离测试与11项smoke通过，另1项公开decoder安装步骤不完整；随后修复owner残余。两份中间包SHA与回归失败记录已保留，不冒充最终包。save两个变体均曾二次dispatch（2!=1）；owner残余21个子例曾未阻断，修复后37项专项全部通过。再次完整构建/审计/回归/12smoke使用上述最终SHA。

## 仓库、上游与限制

私有仓库 `ctzlyj/heideng-ops-agent-merchant-skill`，分支 `codex/merchant-foundation`。内部只读基线仍1.5.4 / `13692b759bd52e35c3670cf8fad5330e1bf2b576`，工作区干净；没有修改其源码、安装或分发方式。视频上游0.3.0 / `29548089f7b71ac77ddb584caac0966a98df24ab`，生成服务等待用户指定。

真实商家OAuth、原生动态卡、网络视频上传、平台审核和商业视觉/声音验收均未运行；没有真实商家写入或付费模型调用。Task3、整店批准写入、驳回修复/短标题、多类目兼容及公开分发/商业权利仍未完成。goal继续active，不宣称整个商家版已正式上线。
