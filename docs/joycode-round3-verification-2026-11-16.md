# JoyCode第3批验证（开发版本0.1.2，2026-11-16）

## HD-2026-11-16-005：关闭

来源为本轮用户提供的商家反馈：JoyCode/macOS15.8.1 x86_64/Python3.12.16，在ed40310安装、rollback、再安装输出均保留credentialExecutionAvailable=false，相关负向脱敏测试通过。按该实机反馈关闭；不是开发者自己在macOS复测，也不把它当作其他平台/店铺授权已验收。

## HD-006：版本流程与安装指引

生产版本同步升到0.1.2；同版本不同SHA仍被same-version-different-artifact阻断，原安装收据不变。失败输出明确updateAction=obtain-newer-version、rollbackRequired=false、sameVersionReplacementAllowed=false，指引取得更高版本核验包，不自动rollback→install或改收据绕过。

包内内容变更的可安装开发源码必须升版；tests/docs中不进入包的纯测试记录无需单独升版。没有正式Release或不通知商家不是漏升版的理由。

RED：原0.1.1源码对已安装0.1.1的新内容直接安装被拒绝，且没有新指引字段。GREEN：0.1.2可直接升级；相同版本改内容仍拒绝，用户状态与安全保护保留。四份版本元数据一致。

## HD-007：规范化测试期望，不改产品resolve

任务自有真实目录符号链接作为临时目录入口，原有JoyCode默认路径及显式skills-dir两项断言均RED；改为resolve后的期望值后，在同一真实链接目录GREEN。加入永久回归；本轮实测是Windows系统的真实链接，不冒充macOS实机，macOS仍待商家复测。没有放宽安装链接或路径安全保护。

## 冻结源码验证

```text
python -m unittest tests.test_release_feedback tests.test_install_host_feedback tests.test_install_entry tests.test_distribution tests.test_updates tests.test_safety tests.test_auth_host_lifecycle tests.test_cli.CliTests -q
```

74项相关回归通过。只覆盖安装/更新/分发/路径/版本相关CLI与授权生命周期，不重复全业务验收；暂存源没有短标题实验。

从Git a3d867256ee7ff94f4b5b11a0ecded78e41c9bd7取出可分发源码，在临时home中用原install.py安装真实旧0.1.1，再用冻结0.1.2 install.py直接升级，重复安装unchanged、完整性及已安装onboarding版本0.1.2通过；没有先rollback。升级冒烟从候选VERSION读取目标版本，后续递增不用把断言固定在0.1.2。

临时验证包122个payload文件（含manifest审核123项），个人路径/凭据模式/未知文件0；SHA256 fc086b0b6f45f1d1a4fbc8a536873168825ac74fb271df8915c2482b06514583。临时包不作为正式发行物分发。

## 边界

没有真实macOS开发者实机测试、CLI下载、新授权、店铺写入、付费或凭据访问；没有操作商家实际home。内部版本不改。只推送开发源码，不建Release、不联系商家、不替换原dist0.1.1 ZIP，其SHA256仍为7cf2d935cd50e652727883ba6b6cab8d0731c7e56c7424b878600ca843b61b34。
