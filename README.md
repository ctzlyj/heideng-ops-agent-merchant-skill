# 黑灯运营智能体商家版 0.3.0

直接迁移成熟 Skill 的业务源码，只保留独立安装、商家状态/授权隔离、外部模型和宿主薄适配。旧 `builtin-independent-merchant-runtime` 及其重复授权/标题/商品业务模块不再打包或派发。

## 从零使用

由宿主 Agent 执行：

```text
python install.py --host codex --with-runtime --with-official
python scripts/merchant.py run connection -- ensure-shop --shop "目标店铺" --no-auth
```

JoyCode 使用 `--host joycode`；WorkBuddy 等使用其实际 `--skills-dir`。商家只需描述目标。已有商家授权优先复用；首次新授权先取得具体许可，再按成熟同会话扫码/OAuth 完成连接。后续直接说“维护信息分”“生成并自动导入短标题”“复刻链接上架”“比价”等，Agent 按 SKILL.md 派发原实现。

图片使用商家自己的 LTS4AI Key、gpt-image-2.5；不使用公司凭据/额度。外部 AI 视频生成尚未配置，但已有合格候选可通过成熟本地交接与上传绑定链处理。独立文本/视觉 API 未配置时，使用原宿主生成文件路线，不静默回落公司渠道。

来源、精确版本/commit、逐文件差异及许可见 `registry.json`、`mature/*/provenance.json`；最终迁移对照与边界见 `docs/merchant-mature-delivery-0.3.0-2026-11-17.md`。

## 交付和边界

- 新内容使用独立版本 0.3.0；同版本不同包、降级与完整性保护保留。
- 原内部版、原商家分支及其未提交短标题实验不改动。
- 用户已要求不再做任何额外验证，本次不重跑成熟测试、不安装演练、不执行新授权/店铺写入/付费生成。前期本地记录不是本次商家真实验收。
- 不创建 Release，不公开仓库，不通知商家。现有 GitHub 验证工作流仅手动触发，本次不触发。
- 平台账号/品牌/类目权限、宿主实际浏览器和外部视频生成配置是实际环境输入，不靠新状态机或假回执解决。
