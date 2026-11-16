# 大请求与京麦 CLI 版本（2026.11.207）

沿用一键上架1.2.6已经验证的方案，在本Skill内复制并适配相同接口检查逻辑，不导入或依赖其它业务仓库。

## 路由

小body直接用官方 invoke --body，按UTF-16单位判断，阈值30000并同时检查完整转义命令长度；大body从本地文件发送。图片Base64上传、完整属性补全PATCH、素材绑定POST可能超过Windows命令行限制，不能擅自拆分接口定义的整体payload。

只有执行官方提取组件时需要真实Python3.12；非3.12执行前就停止，绝不在3.13宿主加载bytecode。CLI本身的查询/审计/授权、小请求、本地生成和浏览器导入/抠图不依赖这条发送路径。

## 接口检查而非版本白名单

jdo_bridge_probe.py保持原方案的probe_runtime/needs_bridge/find_bridge_python/bridge_status接口。子进程静态检查cmd_invoke存在、形参数、实际使用body/params/method/dry_run/path_params/profile/skill_id/request_identity/timeout/url/yes；官方有些字段在辅助函数通过getattr读取，所以只静态遍历相关代码对象，不执行辅助函数。登录兼容额外检查cmd_login读取profile/shop_name/no_browser/timeout。未检查通过不加载到当前执行宿主。

结果按运行时SHA-256指纹和所需字段契约缓存，新的运行时不借旧版本结果；指纹不是可用版本白名单。短暂子进程错误不缓存，CLI文件改变后同一客户端重新验证。0.3.4与0.3.7的真实运行时均已只读检查和dry-run成功。

## 人话自检

大请求不可用只改变capabilities.largeRequests和涉及大请求的readyForMaintenance，不改变environment/read-only就绪。提示只讲受影响、照常可用和下一步；公司策略阻止3.12安装时联系IT或维护人，不报内部校验术语。

## 安全和未知结果

只执行官方CLI账号处理链，不自行读取凭据或实现签名。保持独立Profile、店名和venderId核对；禁止default。小/大路径共享响应分类，传输失败或缺明确成功视为结果不明，不重试写入。dry-run只能返回不含组装签名资料的摘要，不把预演说成平台已受理。现有OAuth回调state核对保持不变，没有兼容3.12宿主就用官方CLI授权。

本次未升级本机CLI、未改Profile、总调度或店铺连接Skill；未进行真实写入或付费生成。只把官方0.3.7下载到任务目录校验，与0.3.4并行验证。
