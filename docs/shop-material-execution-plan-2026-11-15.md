# 整店素材批准执行实施计划

> 执行：使用executing-plans按以下任务内联实施，最后独立requesting-code-review；仅合成数据。总体goal继续active，不把该阶段定义成全部完成。

**Goal:** 可用素材进入一次完整整店范围批准，逐商品50SKU分块执行/读回/恢复，缺项完整报告。
**Architecture:** 原整店审计+原SKU原生合同，薄根服务/证明与Operations钩子。
**Tech stack:** 现有Python标准库、官方CLI抽象、原测试替身。
**Spec:** docs/shop-material-execution-design-2026-11-15.md。

1. [ ] 新测试RED：多商品/离线兄弟/不按分数筛选/源不完整/原槽位保护/错店或错SKU/50+3/统一父批准/没有准备好素材的完整余缺。实现根合同、主服务、批准和真实Ops钩子；专项GREEN及原回归。
2. [ ] RED：超时不重提/不推进，原attempt/ack/父批准损坏、journal reset、根子关联和更新门禁、原范围尾部续批、商品或SKU下架/漂移、能力改变。实现独立原件和只读报告，专项GREEN。
3. [ ] RED：Agent CLI真实行为和摘要/分页；加入入口、README/SKILL/registry/references。
4. [ ] 全套隔离回归，fresh-context独立审查（scope限定本次新增/修改），主流程复现所有Important RED→GREEN及独立窄复核。
5. [ ] 新HOME实际安装整店执行smoke：使用已安装模块，完整合成多商品分块/余缺/unknown/恢复不重提，原官方源码签名/完整请求体旧smokes继续验证。最终归档审核与完整安装矩阵。保留中间失败，只重跑明确失败且相同代码/哈希stage。
6. [ ] 私有代码commit/push，实际GitHub固定代码/新HOME/venv/同归档SHA/全套及安装smokes/干净clone；证据commit后报告，无真实业务/付费/公共发行。

本轮不调用内部CLI/SSO/员工账号，不读真实店铺Profile，不改内部源/安装副本，不维护内部SkillHub。业务规则引用现有已审计官方native-product与sku-material来源，当前认证卡和真实多类目链路仍待独立批准实测。

进展：初始14方法/21子场景RED→GREEN；边界3、CLI1、归属1、晚加SKU1均RED→GREEN，原图片上传来源1正向组合测试通过。3项审查问题在主流程3方法/5期待RED复现，修复后24方法GREEN。全490/493回归为中间代码证据，最终完整回归/安装矩阵及独立窄复核另记录。本阶段不按中间包宣称最终交付。

原件丢失残余复现：删unknown子journal/attempt与根，仍留原批准/index/尾部journal时也能换根，已再RED复现。业务门禁补齐所有批准目录/index/同店子journal反向核验；新任务准备仅由本次调用内的临时上下文允许其刚创建的零attempt子ID在根落盘前短暂存在，不能给历史孤立证明例外。25方法GREEN；独立窄复核与最终矩阵另记。中间496矩阵中2项公开解码依赖安装未完成（非业务请求），原诊断保留；该包已被上述源修复替代，不能当最终包。
