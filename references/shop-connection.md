# POP店铺连接与授权边界

1. 只为用户明确的目标店操作，不扫描所有Profiles。先核对官方CLI是否已校验安装。
2. 商家版官方CLI配置放商家独立cli-home，当前匿名init隔离已验证；每店使用非default Profile，独立shops登记。不要修改员工CLI目录、default_profile或导出凭据。
3. 有目标明确的已有授权时，官方工具按明确venderId/Profile引用并实时venderinfo核对完整店名/venderId/shopId/POP类型；不能仅凭本地登记就ready，也不能仅凭两个Profile名称就声称凭据槽隔离。
4. 需新授权：先auth-plan；商家用京麦App扫任务专属京麦网页，在同context继续官方OAuth。私有OAuth URL/state/授权码只在受控工具内存传递，不输出或落明文。平台本人确认不能代做。
5. 禁用--mock-token-on-service-market-block、--print-code、--code、--force等不安全/重复授权路径。回调端口占用不强杀，不操作其他登录任务；超时先看本次存活任务和结果，不重复开启OAuth。
6. 官方签发后实时核验目标。错店不登记、不执行业务；不删除其他店授权。不把“扫码成功/CLI安装成功”说成新OAuth已签发。

当前开发检查点：已实现official下载/init环境隔离、实时身份读取/绑定、auth-plan协议；自动新OAuth接管worker及完整商家实机授权尚未验收。这是明确待完成项，不是商家已可无感连接的证明。
