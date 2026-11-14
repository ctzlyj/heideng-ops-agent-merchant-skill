# 实施计划与执行记录

2026-11-15：用户批准设计和上线实施。图片/视频模型调用来源由用户后续补充，不用内部资源补齐。目标为单一GitHub仓库安装并上手；其余业务完整推进，不缩小为mock目录。

## 执行约定
当前独立目录开发；不另建工作区、不修改内部项目。分支codex/merchant-foundation。假凭据离线测试和匿名官方公开读取；不花钱、不授权真实店铺、不做真实业务写入。

## 任务/文件/验收
1. safety.py/state.py：相对路径、原子JSON、环境过滤、脱敏。test_safety先RED；逃逸/链接/员工Key拒绝。
2. distribution.py/install.py/build_release.py：独立安装、manifest/SHA、候选激活、回执/回滚；test_distribution先RED，覆盖重复装/同名无关目录/修改/压缩包攻击/中断。
3. official.py：官方版本策略、校验后CLI和官方文档、发现配置隔离参数。test_official先RED；匿名假下载/SHA失败/default/错店；真实临时HOME运行--help/--version，不读店铺。
4. operations.py：任务范围批准、提交/unknown、原子去重、独立店铺登记。test_operations先RED；范围变更/未批准/unknown/并发只提交一次。
5. catalog.py/registry.json/SKILL.md/references：8类能力对接官方CLI/合法浏览器/上传报表/本地素材。媒体awaiting-provider；其余不因缺模型停摆。test_cli先RED，证明路由/中文onboarding。
6. workflows.py：经营报表诊断、精确规格比价/调价计划、listing-package实拍准备、素材缺口/主图详情准备、素材价格证据打包、视频文件交接。test_workflows先RED，覆盖完整SKU/真实身份/hash/QC/试听/写入另授权。
7. providers.py/video_source.py：未定模型不调用，外部凭据/schema扩展接口，指定视频源版本/发现校验。test_media先RED；内部provider拒绝/未配置不发请求/不用11190/交接完整性。
8. merchant.py/README/首次上手/例子、CI和打包审核：单仓库安装提示词；干净HOME安装→onboarding→非模型业务闭环；无内部代码/缓存/凭据/个人路径。
9. 测试→本地验证→分发/许可/脱敏审核→私有GitHub推送和发行→真实GitHub下载再安装验收。公开仍单独批准。

## 决策与进度
- 设计已批准，实施开始。
- 在当前用户独立目录工作，不另建worktree。
- 无许可证内部业务包不分叉复制；自有控制层+官方协议+宿主授权浏览器，确保非模型能力独立交付。
- 测试、真实发行安装、无授权官方CLI、商家授权、真实写入分别记录，不能混淆。

## 检查点1（继续执行，不是完成）

已实现独立安全/安装/官方CLI/任务/非模型工作流/统一入口/GitHub更新；60项自有测试和发行内容审核通过。官方0.3.7匿名下载和独立HOME init已实测。源码推送私有开发分支，尚无正式发行。下一轮继续OAuth安全worker、官方原生业务适配和完整远端发行回测，目标保持全部非模型功能上线。
