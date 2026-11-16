# JoyCode capability布尔输出回归（2026-11-16）

反馈编号：HD-2026-11-16-005（JoyCode批次编号，非WorkBuddy的HD-005）。报告基线0.1.1 / a3d867256ee7ff94f4b5b11a0ecded78e41c9bd7。

## 核对结论

与上批授权布尔字段同属字段名过度脱敏；0b256efba7df6abc6d5ca22458bb12a9aec7f16a已将credentialExecutionAvailable的实际bool列入显式公开字段，不需重复修改生产代码。不扩展到所有bool或数值；同名非bool和apiKey/token等仍遮蔽。

本次仅新增真实install.main输出路径的回归测试，覆盖正常离线安装、可选官方CLI准备失败（合成异常）和负向脱敏。Windows、macOS arm64、不支持平台能力均使用本地模拟平台，安装只在临时home中进行；没有真实macOS实机验收、下载CLI、OAuth或凭据访问。

## RED/GREEN证据

将报告commit的redact实现只加载到内存、临时patch install.redact，不回滚源码：三个模拟平台的credentialExecutionAvailable均被遮蔽，新回归测试失败，复现原问题。恢复当前redact后如下22项针对性测试通过：

```text
python -m unittest tests.test_install_host_feedback tests.test_safety tests.test_install_entry -q
```

默认安装输出保留真实true/false；--with-official失败警告路径仍为成功安装且false可读；同名字符串、0/1、对象以及真实敏感字段形状仍为[REDACTED]。暂存源冻结后重复同一22项，不跑全业务验收。

## 分发边界

仅推送开发测试与记录，生产代码不重复改；不替换已发0.1.1 ZIP、不创建Release、不发送商家更新提示。已发ZIP SHA256保持7cf2d935cd50e652727883ba6b6cab8d0731c7e56c7424b878600ca843b61b34。原短标题实验不纳入，内部版不改。
