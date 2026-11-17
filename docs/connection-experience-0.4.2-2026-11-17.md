# 0.4.2 连接体验与更新修复

## 证据与不变量
以afc0ad2/0.4.1为起点；完整核对30条主消息、337条工具调用。修复连接宿主适配，不重做成熟授权/OAuth，不读取或复制Cookie/公司凭据。生图提示词 `_shared_image_rules`、`image_prompt`不改；HD059不实施。

## 实际修复
- `linker.ensure_server`脱离CLI进程组启动，stdin/out独立；宿主短命令退出不等于结束服务。原健康检查、原服务shutdown保留。
- `HostBrowser.observe`不因读取轮次空闲杀死授权；导航/OAuth动作pending时不重放，保留同一actionId接收迟到结果。OAuth pending等待/同Profile核验，不能冒充未提交。
- 同店普通重试不返回旧failed/mismatch job；显式resume仍走原job.resume先核验。不自动cancel、不混店铺Profile。
- 京麦登录页改为passport.shop.jd.com/login/index.action，不强迫扫码。风控新增account-risk-blocked及去京东商城App验证指引。`browser_bridge`区分缺包环境、控制器与回执错误，默认20秒API超时；不再把缺包吞成action_unavailable。
- 新增`heideng_merchant/host_connection_controller.py`与安装入口：商家owned profile、contextId、Chrome/Edge/Chromium类型、页面观察、OAuth当前范围确认与关闭。内置控制器替代实测时宿主临时编写的CDP常驻服务/confirm脚本，不代替宿主规划业务。
- update在宿主缺cryptography时切到准备好的runtime解释器；不静默安装。
- 商家版自身旧`lts4ai.key.dpapi`可原子迁移到新路径，保留旧blob，不读个人/公司凭据。
- 盘点增加generationEstimate：SPU、SKU槽位、出图槽位口径分开，不能将SKU缺口直接说成出图张数；原提示词不改。
- 文档说明JSON文案与XLSX导入校验不同、宿主控制器入口、更新运行时及最终源码==固定包发版纪律。

## 验证
本轮离线套件覆盖连接、Key、更新、安装和真实本地服务生命周期。假店铺/隔离本机服务只证明适配，不证明真实京麦身份、扫码、风控或OAuth已完成。没有真实店铺写入、扫码、改价、消息、付费生成。

新增`test_release_consistency`要求最终源码重建与固定ZIP逐文件和SHA256一致；发布后才编辑包外证据文件，不能改变入包registry/manifest造成0.4.1同类问题。

## 剩余真实内测
WorkBuddy真实进程回收、Chrome/Edge实际窗口、京麦登录、风控页、OAuth、Profile注册、后续素材复用；macOS浏览器/Keychain。已把“本机控制器可运行”与“真实商家通过”分开。
