# 整店素材修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 商家描述整店修复目标后，Agent能把可验证的新图/文字用于原驳回或空槽，统一批准执行与恢复。
**Architecture:** 新增独立修复证据模块，原v1不变，有修复时创建v2与审计/旧图字节证明，复用根执行状态机。
**Tech Stack:** Python标准库、原官方jdo接口适配、原受限CDN下载器、unittest。
**Spec:** docs/shop-material-repair-design-2026-11-15.md

## Global Constraints

仅合成业务；无真实OAuth/API写入、模型、消息、内部服务或公开发布。当前工作区开发，内部包只读。图片/视频生成来源仍等用户确认。

## Review Focus

旧审核状态单独变化；新URL却旧字节；缓存丢失/篡改；根/子混用修复证明；unknown后换根重提。

### Task 1: 修复合同与执行闭环

Files: 新增heideng_merchant/sku_material_repair.py、tests/test_shop_material_repair.py；修改sku_material_contract.py、sku_materials.py、shop_material_execution_contract.py、shop_material_execution.py；原state不改变格式；workflows.py旧下载器只增加require_complete显式选项，默认采集路径不变。
Interfaces: repair_fields(ops,baseline,audit,changes)返回v2证明增量；validate_repairs(ops,proof,sources,live=False)校验资格/字节；repair_allowed(content,evidence)纯资格判定。

- [x] 写文字/图片修复、拒绝旧批准/待审/未知/相同文本/字节、审核漂移/缓存损坏、多商品分块和unknown测试。
- [x] 运行新增测试，保存RED；实现最小闭环后GREEN。
- [x] 运行原497测试与新增测试，保证v1历史与根安全不回退。
- [x] 写安装smoke，实际安装新包并运行混合填缺/修复；只模拟原生请求/原图下载，不模拟安装模块。
- [x] 独立审查、复现修复发现，再跑相关测试与全套。
- [x] 更新README/技能与参考、证据，脱敏/包审计后私有分支提交推送。

短标题、远端既有视频采纳、真实商家验收和许可仍为后续工作，不用本轮通过替代整体目标。

复核记录：两原P1及同一全集排除P1残余均主RED→GREEN，19新持久方法；独立10方法最终PASS。最终完整516与4smokes当前在同一源码上复核，原515/pre-residual矩阵不得冒称当前通过。

最终本地：516测试、4相关安装/官方源码smokes通过；完整测试第一次旧视频会话准备非ready，单项6次窄复核及同源码第二次完整通过，原失败/未区分底层原因保留。不改源码或断言为重跑转绿。包审计83文件，个人路径/凭据模式/未知文件均0。私有推送及实际GitHub验收回执另存，不冒称公开上线。
