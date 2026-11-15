# 原范围短标题原生健康来源：私有研发验证（2026-11-16）

本阶段只补齐 C3 的一个必须来源，不是商家全流程上线或正式导入验收。正式短标题审核、门户、确认失败修复、完整 terminal/更新门禁和真实商家验收仍待完成；模型提供方与商业分发许可仍待用户决策。

## 修改与行为

- `ProductService.health_detail` 使用已核对的原生健康详情路径；`short_title_health_sources` 在原 SKU/product 范围内投影和验证全量列表与逐 SKU 详情。
- 原 owning worker/guard 中前后读取完整原兄弟范围，包含离线、缺列表行和缺详情，不另开浏览器、不改变已上传 live binding。前后观察不是服务端事务快照。
- v2 健康证据只提供 nativeHealthSourcesVerified 与 targetHealthRequirementsSatisfied。formalAuditVerified、portalVerified、healthVerified、imported、retryAuthorized 均不能从此变 true；当前健康来源标志不接受历史回执替代本次读取。
- v1 原件继续严格保留；v2 不能通过后续 v1 降级丢失。旧列表分数和问题事实不被详情字段悄悄替换；legacyFacts 绑定 SKU/product/hash/分数语义/问题，并重建旧行和 page hash 声明。
- sourceData 签名资产 URL 只在内存参与来源 hash，不输出、持久化或获取。仅文档指定位置的合法 HTTP(S) 资产 URL 允许隐去后检查；URL userinfo 及其他位置的凭据字段使整次观察拒绝，不能按单行缺失吞掉安全错误。

## 原生契约依据与限制

公开官方发布策略及 18 份商品 price/status/update/material/publish 文档逐项 SHA256 验证。策略 hash 为 `acd1914caceebb8c00e24d98ee587fbaddefe3ab75f74eabd2fe782398e1c424`，字段文档 hash 为 `3d049c742490d73665ac1ae57b182fc6add0b574319c62edd764b3594d43688f`。观察时策略声明 CLI 0.3.7、Skill 6，不能据此声称一直是最新。

确认详情路由 `/rest/sp-product/v0/health-infos/{healthInfoId}`，healthInfoId 对应原 SKU。上述文档未发现专用短标题正式审核或门户契约；这不是不存在 API 的证明，商品 bossAuditStatus 不能替代。原始第三方文档仅在忽略的研发临时目录，不进入 Git 或分发包。

## 实際验证及保留失败

最终定向回归：89 方法通过，0失败/0错误/0跳过，222.516秒，226份源码/参考文件 hash 未变。当前发现766方法，**本阶段没有运行全量766**。旧固定 GitHub commit 的745方法通过只适用于 `dc4590a29e8f2d110849080bf2c913bfb5efc5d9`，不是当前健康版本验收。

新 HOME 安装 smoke：3方法通过，默认 managed-install verifier、实际 owned localhost IPC、合成 browser/client、完整5个原 SKU 详情、v1历史保留/v2降级拒绝。真实商家调用和付费模型均为0。

最终研发 archive SHA256：`605bf4c44275047a3ff9f1dd0b7a2625705bf601edf24cf9e0c36e3a03fe36db`。115源文件、116文件含 package-manifest；全部 archive 源文件与当前源码的规范化换行字节匹配。包审计通过，个人路径/凭据模式/未知文件均为0；这是模式和路径审计，不替代分发许可审查。

独立限范围审查曾发现 legacy 声明未绑定和签名列表投影错误，实际两方法 RED 为3失败+1错误；修复后复查通过。随后选定87方法中旧凭据回归实际1失败（223.719秒），保留该失败；修复后88通过，但不能冒充最终 userinfo 修复后的验证。userinfo 新精确测试先实际1失败，再修复；最终89通过覆盖全部上述回归。交接记录的最后独立隐私复查7方法通过（9.024秒），没有该范围的新 Important/Critical；这不是新全分支审查。恢复后尝试关闭原 reviewer，当前工具已无该 agent，不重复启动它。

记录脚本最初因错误猜测 manifest 名称、随后默认GBK读取中文审计资料而失败；只修正证据脚本为真实 package-manifest 和显式UTF-8后，源码/包/18文档核对通过。两次证据脚本失败不算业务测试失败或通过。

## 隔离、仓库与下一步

私有仓库 `ctzlyj/heideng-ops-agent-merchant-skill`，分支 `codex/merchant-foundation`，起点 `939be03c26cb1cca60e2565b0973487a32595346`。本阶段仅私有开发推送，不创建公共release。

内部版只读、git status为空，1.5.4 / `13692b759bd52e35c3670cf8fad5330e1bf2b576` 未动。视频上游本阶段未刷新；审计基线0.3.0 / `29548089f7b71ac77ddb584caac0966a98df24ab`，不称最新。没有真实OAuth/jdo/API/登录浏览器、店铺写入、模型、消息或公共发布。

继续发现并核对正式短标题审核/门户契约，不猜接口；随后补原根已确认失败子计划、当前真实修复需要与新精确批准、terminal与安全未尝试恢复、跨版本重建。统一当前全量回归和新固定GitHub安装验收安排在实际完整C3/失败worker检查点。健康证据检查点不解除隔离、不自动重投，也不结束整体目标。
