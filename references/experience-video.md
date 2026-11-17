# 已有视频交接、上传与绑定

## 两件事不能混为一谈

- **外部 AI 视频生成渠道尚未配置。** 不能调用公司灵境/模型/额度补齐，不能静默改成拼接，也不能说已能商家AI出片。
- **已有真实成片的本地交接/上传绑定是已迁移的成熟路径。** 不必先配AI服务；需要真实来源、文件/封面、符合原契约的复核记录及正确店铺商品映射。

## 事实与参考路径

需要实际 listing-package（对应工具的schema/status/productId/SKU集合）、候选视频/封面、真实模式/来源任务（AI时）、QC/口播信息、用户本次交接或绑定范围。

通常先读取已有包与候选，不扫描目录猜另一个文件。原 local publication 接受该run下真实候选与真实metadata，原子发布视频/封面并写回manifest；不是手填SHA/自动pass假造已完成。

- `run video-handoff -- publish <包> --run-id <真实run> --video <该run候选> --cover <真实封面> --metadata <实际复核记录>`。
- 原候选路径为 `<包>/.main-video/runs/<runId>/candidate/`，原发布实现负责完整性和唯一文件。缺真实QC/口播等字段是该交接契约的具体缺项；宿主可做实际复核/获取合法证据，不能填默认“通过”。
- 交接后按原 `run video-binding -- --manifest <包内manifest.json> --confirm BIND_MAIN_VIDEO`，沿用原规范检查、店铺/商品/SKU核对、试听（确需时）、上传保存/转码/逐SKU绑定和回读。
- 源链接视频也可由原 mover automate_main_video 处理；不是所有源包都等同于photo_video的listing-package契约，不能改schema/status伪装。

同一范围已有明确批准按原工具传递，不因“本地交接→绑定”增加黑灯层重复批准。口播试听/接受风险要求是原特定内容确认，不能用泛泛“确认”编造试听；本文件改变后原同文件确认失效。工具发现SKU已绑定其他视频时不自动覆盖。

## 完成证据与未知恢复

本地交接完成不等于店铺已绑定；上传不等于转码/审核完成；同店逐SKU绑定与对应平台关系/审核回读才证明该范围结果。记录真实 taskId/videoId/关系状态和文件SHA，不生成假任务ID。

TRANSFER/SAVE/BINDING结果未知先查原请求/已保存videoId/关系，按原状态继续；不得再次上传同一未知文件或换工具重绑。只读查看已有视频不要求生图Key或付费生成许可。

## 来源与限制

本地发布来源 jd-main-video-batch-skill 1.1.3 / 40d664e：[原发布](../mature/video/scripts/video_publication.py)、[本地入口](../mature/video/scripts/local_handoff.py)。上传绑定来自 mover 1.2.6 / 3ee08af：[photo_video](../mature/listing/scripts/photo_video.py)、[handoff](../mature/listing/scripts/video_handoff.py)。没有复制公司生成器。

本轮未执行真实生成、上传、绑定或试听验证；真实文件契约/平台审核/权限依然适用。其他合法商家已授权视频工具可由宿主使用，但不是绕过未知写入或模型/费用选择的入口。
