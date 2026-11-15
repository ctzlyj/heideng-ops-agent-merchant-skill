# 商家短标题自动导入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax.

**Goal:** 一个GitHub包中的Agent可自动完成有确切问题的全店短标题导入、原件恢复与真实范围验证，而不是让商家手工上传表。
**Architecture:** 原完整库存/health来源用于规划；独立安全模板编译；随后任务自有浏览器取当次来源及精确批准，独立原件/未知恢复。
**Tech Stack:** Python标准库、原ShopMaterialAudit/ProductService、原BrowserRuntime/Playwright（B阶段）。
**Spec:** docs/short-title-import-design-2026-11-15.md。

## Global Constraints

仅合成业务，无真实授权/平台操作/模型/付费/消息/公开发布。当前商家根开发，内部和个人Skill只读；不复制内部xlsx/凭据/profile。原开放工具箱定位不缩为能力白名单。

## Review Focus

派生标题问题与原health矛盾；健康分缺失/素材失败导致漏库存；模板中残留示例/危险内容；超大SKU文本精度/静默截行；把规划/表格或job类型ID称写入成功。

### Task A1 完整来源与规划
Files: 新heideng_merchant/short_title_contract.py、short_titles.py、tests/test_short_titles.py；CLI只增加plan/status/rows。
Interfaces: source_context(state,auditId,fingerprint=None)返回原记录/完整标题覆盖；ShortTitlePlans.prepare(auditId,changes)只本地冻结；status/rows为紧凑历史摘要/分页，无写入批准。
- [x] RED测试原问题推导、分数无关、素材失败仍完整、错店/离线/原关系/未知/源漂移、完整余缺与5000分块。
- [x] 最小实现并GREEN，全套回归。

### Task A2 安全模板编译
Files: 新heideng_merchant/short_title_workbook.py、tests/test_short_title_workbook.py、安装smoke；无xlsx进入安装包。
Interfaces: compile_template(templateBytes,rows)返回安全完整xlsx bytes；plan.compile(planId,templatePath)保存每块中间产物并核对原行/hash，不宣称来源或写入已证明。
- [x] RED→GREEN：保留表头/格式、清除样例共享字符串、SKU文本精度、宏/外链/DTD/路径/重复/体积/错误表头/公式/多表拒绝、5000/5MB边界。
- [x] 新HOME实际安装CLI、模块路径与本地规划/编译；规划不能执行业务。
- [x] 一次独立有界审查、修复/复现、最终全套和包审计，私有代码推送及GitHub往返证据（A1/A2：fa477dd代码、d7ac816证据；539+4）。

### Task B/C 完整自动导入（A之后继续，不视为可选）
- [x] B1内部只读取证adapter与独立原件：任务自有持久profile、当次request/main_frame身份/模板/任务页、版本切换互斥；25 core+5 gate方法和6Important独立复核通过，ad0d573代码。不是完整浏览器写链路。
- [ ] B2/C CLI/worker接入、同会话当前来源实测、完整任务分页契约、必要商家扫码；B1尚未暴露这些能力，不借凭据。
- [ ] 精确根批准、上传/创建实例、分块attempt/ack/anchor、截止时间与unknown只查不重传。
- [ ] 实例逐行结果/仅已确认失败行修复、原范围健康与原标题/审核回读、更新/回滚门禁。
- [ ] 完整安装/GitHub验收，真实链路与许可另确认。

A阶段五项独立Important已主RED→GREEN，23新持久测试通过，独立六不变量最终PASS。新增siblings视图和准确模板关系/namespace保留已进入安装smoke。B/C保持未完成，不能把A阶段指纹/文件当写入授权或导入成功。最终本地/实际GitHub回执另存。

B1本地最终569+5已通过；实际GitHub同commit569+5重装已通过，见docs/short-title-browser-source-verification-2026-11-15.md。整体goal仍active，生成来源待用户选择，B2/C和真实商家/类目/规模与权利验收仍未完成。
