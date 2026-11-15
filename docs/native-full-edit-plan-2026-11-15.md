# 既有商品整版编辑与回查实施计划

2026-11-15；基线 c8ab00ce979c36bd2c28d04575d720ceedff81b6，当前私有分支/工作区。上一轮为进展。自主实施，不触发真实商家授权、写入或模型生成。

## 设计与裁决
目标是完整旧商品、全部 SKU 的图片/详情整版编辑及原申请单/线上回查，而非只标记一份草案 ready。采用 source-provenance baseline：保存经隐私检查的完整原详情和实时模板；host 按公开规则生成 business DTO 及逐值来源绑定（商家不手填 JSON）。来源必须是同 capture 原详情的确切字段，SKU 按真实 skuId 选取而不是数组位置。SkuId/SkuUUid 使用真实 ID，outerId/price/stock 保留，颜色 mappingId 从原属性记录读取（为空用 attrValues）。完整组件、全部原 SKU、未知 business 值不得漏掉。

Ruling：不把 label/inputType/devTips/childrenComponents 当作提交 DTO，也不删未知 business 值。源模板保存在 capture，提交只按官方 componentCode/value/properties 投影；host 填值必须有完整原字段来源证明。不能证明原值或完整结构时拒绝，不能靠数目相等、UUID 或默认值冒称 ready。未填充的模板兼容性仍需真实授权 schema 验证，不用 mock 宣称普适。

Ruling：价格/库存/规格不在本轮图片/详情修改范围；完整保留并回查，必须只更改用户明确图槽/desc。source bindings 和 live provenance 同时进入批准范围；source drift、原图回执变化、错店和未知原提交阻断重放。

## 任务
1. capture 保存完整非敏感原详情。新增 edit_contract：完整 DTO 结构/所有值来源、实际 SKU 及销售属性身份、原字段更新后比对。
2. EditService.baseline/plan_validation/plan_edit：仅替换明确图片槽或安全 HTML，完整原 DTO 不删除/重排；验证仍为有批准 POST，正式整版 POST 带原 productId。共用已有校验 verdict/原回执 SHA/600 秒/最后 deadline/stdin 边界，普通 task-plan 不可绕过。
3. 同本机同物理店铺编辑意图/校验 nonce 去重与旧 prepared supersession；media 上传来自同 Profile 原回执，不借文件名或临时链接。
4. status(refresh)：仅用原 applyId 对应申请单、原 productId 回查；所有原值与明确修改字段、完整 SKU 集合相符才 pending/online verified。未知提交不因当前状态匹配清除，受理不等于线上生效。
5. CLI/registry/参考：Agent 自主组合，商家仅目标/必要授权确认。新 image/desc 输入严格 JSON 和安全 HTML，费用 provider 仍未启用。
6. RED→GREEN；一次有界独立 review；完整 suite/安装包/1000 SKU 安装后合成 full-edit + 新品/旧素材/价格回归；私有代码推送后真正 GitHub clone 重建 SHA/安装回测，再提交证据。不得用这些替代真实商家链路/正式发行许可。

实施过程已观察边界 RED→GREEN：别处相同值伪造标题/未知字段来源、未知 DTO 外字段被静默删、未回查的已知编辑绕过写锁、最后 SKU 外店父商品、规则子组件颜色分类遗漏、重复属性。来源声明用原 capture 元数据/已核实 native 字段，不接受 caller 改写声明。无维度 SKU 保留已证引用，不造颜色；所有未知 business blob 值仍需原完整字段证明。


## 独立评审与最终收紧
一次有界只读评审确认 3 项重要问题，均以失败测试复现后修复：critical SKU 分支允许 HTML 转换暗改 outerId；完整回查未重验 attrId 和当前 mapping/fallback；额外通用 verification 可提前解锁整版任务。已限制关键字段只做已核实无损转换、回查重验全部 native 销售属性身份/census/mapping、禁止整版任务绑定通用局部回查并保护旧 verified-but-no-full-evidence 状态。

追加实测边界：原销售属性 sibling census 不能漏项；价格/库存/编码必须有 value；仅 WareEditor/detail 的 desc 可编辑；未知 JSON 数字不能随意转成字符串；带 componentCode 的 opaque business array 不当作 DTO 删除字段；原 null 详情保留、不编造 HTML。只有已知或实际声明的组件容器按 DTO 投影，未知 business blob 完整按原字段绑定。

Ruling：模板字段声明不完整、纯规则模板尚不能证明全值/结构时拒绝；完整通用填充器、实际线上数据语义/真实商家链路和正式发行许可仍不由本次 mock 证明。安装烟测修正了 fake adapter 的类替换、state 路径和 productIdList 参数形态；原柄终态确认后才重跑，均非真实业务调用。烟测固定输入 ZIP 的本地副本与 SHA，避免并行构建误配安装证据。

## Windows 安装切换排障裁决
新增烟测在业务命令前间歇出现 install-switch-failed-recoverable。仅离线合成环境插桩确认失败点是 stage→target 的目录 os.replace，errno=13 / WinError=5；路径长度及预创建合成 state 对照未证明稳定关联。后续 120 次插桩对照全部成功，因此不能指认具体占用进程或声称自然失败每次稳定复现。原生 Windows CreateFileW 无 FILE_SHARE_DELETE 的子文件句柄可确定性复现相同目录 rename 失败；释放后同源目录无需修改即成功。

Ruling：仅对本地已验证安装目录的 WinError 5/32/33 切换做至多 6 次调用、5 次退避（总计划等待 1.55 秒），源目录 inode/device 必须不变，目标必须持续不存在且双方不得变为链接。持久失败保留 journal/备份；非 Windows 错误不重试。这不是业务 HTTP 重放，真实店铺/生成请求的 unknown 不重放契约完全不变。无法确认实际句柄持有者，文档不归因特定杀毒软件或后台。

7 项新增回归先观察 RED（无重试导致 native/注入锁失败、持久失败仅 1 次），修复后 20 项安装测试 GREEN；覆盖原生句柄释放、持久失败上限、非 Windows 错误、目标出现/源替换保护、升级与回滚。正式最终包 SHA 需重建并重跑整个矩阵，之前 dd388... 包的结果不冒充修复后的验收。
