# 原生图片素材开发验收（2026-11-15）

这是独立商家版的素材空间链路，不是商品主图/详情绑定、全SKU上新或整体正式上线。0.1.0仍未发行，真实商家权限/上传未实测。

## 实现与协议

新增Pillow-only独立ImageRuntime、stdin完整解码、原图SHA/尺寸/格式/帧证据；原图不改写，坏图/异常像素拒绝。复用公开运行时控制但不改browser runtime包和回执。新增空间/分类/图片分页/详情、扁平imgBase64+zoneImageDTO计划、同店活动分类检查，通用task-plan也强制该图片上传契约。

resultVerification只从原已知回执解析安全顶层ID，绑定原批准GET及固定字段，保存原结果哈希检测被改回执；unknown不能由现状匹配或模糊名称关闭。图片imgId/JFS/名称/尺寸/格式/分类需原回执及GET一致；CLI省略结构化和JSON文本base64，实际请求留本地状态。storageVerified与productBound/remotePixelsVerified分开，后两者一直false。

## 实际验证

- 完整fresh HOME/clean Python3.12 venv、-I/-B离线套件：**193项通过**，测试进程socket connect拦截，不是OS防火墙。
- **47文件**分发包审核通过（46源码/参考文件+manifest），个人路径/常见凭据模式/未知文件匹配0；不是第三方runtime全部脱敏证明。
- ZIP SHA：`16314568bd011be0cbbb8fa260f54451c6e17ea89398505f13d1da4e81c765ae`。
- 真实公开PyPI **Pillow13.0.0**独立安装；2x2标准PNG原bytes完整解码/SHA一致、3个坏图拒绝，未重写图片。
- fresh HOME校验ZIP真实安装，真实Python -I/-B跨进程命令与Pillow原图解码，196992-byte有效256x256 PNG：素材flat POST、无批准不上传、原imgId回查、已知1次与受理后丢响应unknown1次、不因名称/新计划解锁、CLI不输出base64均通过。业务API为file-fake；命令主进程socket阻断，图片child为本地解码代码，不是OS全进程网络封锁。
- 安装后旧价格file-fake回测仍通过，待审/线上/unknown区分且不重提。
- 内部1.5.4 / `13692b759bd52e35c3670cf8fad5330e1bf2b576` Git干净，未改。视频最后审计0.3.0 / `29548089f7b71ac77ddb584caac0966a98df24ab`，本轮模型调用0。

## 单次评审修正

无Critical，3 Important、1 Deferred Minor。JSON文本base64回显、无分页证据短页假全量、无int64依据的正数分类限制，均先观察RED再修复；20项针对性回归及193项全套、安装后smoke通过。最后修正没有第二轮独立review，不能把本地GREEN说成再次独立评审通过。

## Rulings I made

1. 分类ID服从int64及本店实际返回/活动状态，0/-1可在被实际返回时使用；不猜默认根，也不声称实际账号一定有0分类。成本：不能仅凭正负判定合法，必须实际读本店。
2. 缺分页metadata/total即partial，短页不证齐全；成本：未知账号需继续查schema/来源证据，不能直接报全店完成。
3. <3MB解释为base64编码后3,000,000 bytes，原图不改；成本：大图需另做核验派生文件，不静默缩图或扩大平台限制。

## Deferred minors

文件stat之后仍用read_bytes，增长/替换时存在超限分配窗口；末尾尺寸检查阻止上传，但不阻止已经发生的分配。没有复现误提交，后续做限长读取，不把此项隐藏为已修复。

## 未验收与下一步

未读真实merchant凭据/刷新，未执行真实店铺上传/OAuth、JFS下载像素身份、商品图片绑定、全SKU上新、付费生成或正式Release/远端CI。下一步继续以原生商品申请协议接素材到主图/详情/各SKU及完整上新，保留完整范围、旧新值批准、待审/线上分开。模型来源继续awaiting-provider，完整目标active。
