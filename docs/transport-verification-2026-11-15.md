# 官方大载荷 transport 开发验收（2026-11-15）

整体目标仍在实施：本检查点解决大图片/大上新JSON的载荷传输，**不是图片上传/上新已完成**，未建立正式Release。0.1.0仍是未发行候选；正式发布必须新版本和资产审核。

## 实现

官方binary小载荷保留；实际Windows argv UTF-16引用转义后超24000 units，在提交前选官方同版源码stdin。source与binary的version/SHA/官方策略及本地已审计SHA一致，sourceStatus deprecated明确写入任务fingerprint。源码仅内存/管道，不复制到项目或日志，不重写签名，不用内部Key或员工平台。Python -I/-B独立worker，Windows Credential Manager；macOS仍禁带凭据执行。

scope记录officialExecution和原批准店铺，拒缺契约旧批准。耗时预检后再核店，worker用同一冻结认证上下文的官方签名seller-info GET核验完整POP身份，随后只用该上下文执行原业务请求。期限在实际HTTP前再次核对。未知不能换transport重提，worker关闭写transient/auth-marker重试。stdout/stderr有界内存捕获，关闭源log/telemetry；请求回显和秘密JSON键/值不发布。

## 单次评审与修正

独立review无Critical，3 Important、1 Minor。旧批准省绑定、预检换店、成功JSON载荷/秘密键回显三个原路径均由失败回归复现再修复；最终修正是本地回归与全套/实际SHA源拦截网络验收，没有另开第二轮独立review。

## 实际结果

- 完整clean venv/fresh HOME、Python -I/-B、socket connect拦截的离线套件：**170项通过**，不是OS级防火墙。
- 分发包39源文件+manifest，**40文件审核通过**，个人路径/常见凭据模式/未知文件匹配0；不代表第三方binary全部脱敏。
- 包SHA：`820693e3b3b4d74032cbedcc06206a52c054ac1f7bef33ab48ec6221ff7a0a1a`。
- fresh HOME校验ZIP实际安装；从安装副本运行真实Python子进程的同版官方source解析/签名smoke：**通过**。source按官方SHA核验、仅内存；合成base64 body 900074 bytes，成功/auth-marker/丢响应场景各1次签名身份GET+1次业务POST，无写重试；默认协议入口在空商家命名空间拒绝、不暴露原stderr。
- 所有merchant HTTP在官方代码内部被hook拦截，socket connect禁用；认证为合成hook，**没有读取/刷新真实merchant Credential条目**。不是有效PNG图片上传成功。
- 安装后原生价格跨进程file-fake回测仍通过：未批准不写、待审/线上区分、unknown不重提不解锁。
- 内部版1.5.4 / `13692b759bd52e35c3670cf8fad5330e1bf2b576` Git干净，未动。视频最后审计0.3.0 / `29548089f7b71ac77ddb584caac0966a98df24ab`，本轮模型调用0。

## Rulings I made

1. official public source虽标deprecated，仅用已审计同版SHA的兼容transport，并透明记录、不复制源；若撤回/改变，大载荷停待新审计，不擅自假定第三方分发许可。
2. 旧批准缺execution契约一律重新规划，worker身份签名核验冻结context；代价是旧prepared不能直接续写，身份检查失败也不能跳过。
3. 请求回显不作为正式结果发布；代价是回显字段不能拿来验证业务成功，需另外权威GET回查。

## Deferred minors

worker没有第二次断言JDO_ENV=prod；正常parent已强制，未复现正常路径错环境提交。暂保留纵深防御项，绕过parent独立启动driver不是支持的商家流程。

## 未验收与下一步

没有真实商家授权/OAuth刷新、图片上传、全SKU上新或实际店铺写入、正式Release、远端CI、付费生成。继续媒体空间/分类发现、图片上传/主图详情绑定与原生上新；模型来源继续待负责人补充。本检查点不会将mock工具箱称整体上线。


## 实际私有GitHub回测

代码commit `387e66fded031b2c0921f8603cb9395112939c8a`推送后，实际重新克隆私有GitHub单分支（非本地复制），HEAD匹配，重建包SHA与上面一致；40文件审核、fresh HOME/Python -I安装、onboarding、安装副本的真实公开SHA源拦截网络大载荷smoke、原价格跨进程file-fake以及从clone运行170项全套均通过。见github-transport-roundtrip-2026-11-15.json。仍需要已有仓库读取授权，没有正式Release/远端CI或真实商家API写入。
