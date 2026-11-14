# 原生素材上传与结果绑定实施计划

> 执行executing-plans/TDD，结束做一次有界独立review。沿用已批准架构，在当前独立商家目录，不另建聊天/worktree。

**Goal:** 商家提供已有合规图片，由Agent自动查询本店原生空间/分类、完整规划并批准上传、执行及按原回执图片ID回查；不猜ID、伪造上传成功或因unknown重复提交。图片绑定到商品是后续独立写，不把图片空间保存等同商品主图生效。

**Architecture:** 新MaterialService包装官方media-zones GET与扁平POST。任何该图片POST（含通用task-plan）都强制native upload契约：有效base64、原图SHA/解码信息、当前本店图片空间和分类、回执及result-bound GET。结果ID绑定只有在本任务已知提交回执后解析，不能用模糊名称/当前目标匹配解除unknown。独立按需公开PyPI Pillow运行时只解码已有图，不做生成或访问公司模型。

**Spec:** docs/migration-design.md、implementation-plan.md及本地官方SHA核验api-reference.md。官方字段：zoneId来自media-zones；categoryId来自指定zone categories；imgBase64无data URI且<3MB；保留zoneImageDTO，禁止xxxRequest包裹；imgId/imgUrl/名称/尺寸/分类来自回执与GET。fileUrl只有邀约伙伴，不假设任意公开链接可替代。

## Global constraints / Rulings

- 维持shop+fingerprint+TTL+officialExecution/unknown gate，字段缺失/重复/分页变化必须明确，不截SKU。
- <3MB按base64编码后的3,000,000 bytes严格上限解释，不拿文件原始3MB推断可传。若账户定义不同，需真实授权后核验，不能静默放宽或改图。
- Pillow按当前官方PyPI版本/许可元数据安装在独立image-runtime，不改browser runtime、不复制第三方源/Key。
- 原文件不改写，任务按实际提交bytes SHA批准；重新编码、改主图/详情、绑定到SKU要另按范围批准。
- CLI不输出imgBase64，显示原图SHA/尺寸/名称与scope fingerprint；实际原请求只留本地任务状态，不进argv或源码日志。
- 决不把upload accepted、图片回查、商品绑定、线上生效混成一个状态。

## Files and tasks

- [x] 1. tests/test_image_probe.py/test_image_runtime.py RED；薄ImageRuntime复用公开隔离安装控制但独立Pillow池；新image_probe.py做stdin字节完整解码/像素预算/真实格式/尺寸/SHA探测。实际干净runtime验证。
- [x] 2. tests/test_result_verification.py RED；Operations.prepare新增result_verification，允许仅批准的query路径参数与expected中的$id绑定从原非unknown回执读取；新增verify_result，严格路径ID、原shop、固定字段匹配与unknown不清除；CLI task-result-readback与JSON输入可绑定。
- [x] 3. tests/test_material_contract.py RED；新material_contract.py，所有媒体图片POST必须完整原生契约、真实解码证据/zone/category；prepare和execute各读本店zone/category并重新核验；execute校验已知imgId/JFS回执；verify_result校验同一ID/URL/属性。未知只读保留，缺imgId不猜名称/重提。
- [x] 4. tests/test_materials.py/test_material_cli.py RED；新materials.py及CLI spaces/categories/images/detail/upload-plan/upload-status，保留分页partial；文件bytes进入请求body，元数据进入批准scope；关键过滤只按官方schema可用字段，不是总体能力白名单。
- [x] 5. 真实Pillow/真实ZIP安装+Python -I命令+file-fake API闭环：无批准不POST、错店/错分类/异常图/重复ID拦截、known1次/unknown1次且不解锁；素材保存不声明商品绑定。
- [ ] 6. 单轮review重要问题RED/GREEN、全套离线、包审核、证据、私有push、实际GitHubclone重建/安装回测。整个目标仍active；真实店铺写入/模型另授权。

## Review focus

动态id不能用其他任务/未知回执或额外JSON路径注入；通用task-plan不能绕原图/类别验证；分页partial不能当完整；图片扩展名欺骗/压缩炸弹在本地拒绝；成功stdout不能暴露base64；old approval改变文件/分类/transport拦截；没有真实JFS下载/像素质检时不声称远端图片身份视觉验收。


## 开发进展（review与最终验收待收口）

runtime3项、result绑定5项、上传契约5项、service5项、CLI2项均在RED后实现且GREEN；真实公开Pillow13.0.0在独立runtime安装，标准PNG2x2原bytes SHA/完整解码通过，3个坏图输入拒绝。通用上传入口不省契约，动态回查不借unknown或外来回执解除；CLI不印base64。第一次完整套件已启动，单次有界review在进行；不把这些当真实商家上传或商品绑定验收。


## 单次review与一轮修正

无Critical，3 Important、1 Deferred Minor。JSON文本回显base64、无分页证据短页冒充全量、没有int64协议依据的正数分类限制均先RED复现后修复；包含实际返回0/-1且状态有效才接受，未返回时仍拒绝，不猜root默认。20项定向回归GREEN，准备重跑最终全套与安装smoke；没有第二轮review。

Ruling：categoryId按官方int64及本店实际返回/有效状态判定，不额外要求正值。成本是不能仅以0/负值判断无效，必须实际读取；不声称真实账号一定有root=0。

minor (deferred)：文件stat后无界read_bytes存在增长/替换时的分配窗口，最后的尺寸检查会阻止超限上传但不会阻止已发生的读取/编码；尚未观察误提交，后续限长读取。


最终本地验收193项套件、47文件审核、真实ZIP+Pillow/file-fake跨进程、旧价格回归通过；详见material-verification-2026-11-15。私有推送/实际GitHubclone尚待收口，真实账号上传/商品绑定/整体发行仍未完成。
