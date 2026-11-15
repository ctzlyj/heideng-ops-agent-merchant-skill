# 原生主图视频绑定

Agent先执行已有视频上传/保存会话，再将原会话用于本店同商品完整SKU绑定；不选择生成模型，不重新上传来替代复用。当前为私有研发适配，真实平台验收另获商家批准。

1. `video-binding-preview`：profile、product-id、session-id；复核原视频/封面/manifest、原回执ID、全SKU清点、实际二级类目和当前prod“产品展示”标签。只读返回商品身份确认范围。
2. Agent实际核对商品身份，保存绑定原视频hash、原listing hash、商品详情hash和全部SKU的确认；`video-binding-plan --review …`由Agent调用。缺少/不匹配确认拒绝，商家无需自行写JSON。
3. 展示全商品SKU、原videoId/jdVideoId、只补缺失type42/order1的范围和分块。取得本次明确绑定批准后，`video-binding-approve`保存独立父批准；上传批准不自动包含绑定。
4. `video-binding-execute`最多逐块提交一次，每块<=50SKU，统一父deadline贯穿。只写新增order1，不重新提交其他已审核orders，以免重置其审核；所有已有视频字段/非目标orders和已查询图片/文本内容须读回保持原样。
5. `video-binding-status --refresh`精确读回完整素材范围及原视频完整分页关系。字段匹配、关系可见、原视频审核、素材审核和关系审核分开；status2不等于视频审核，pending/approved/rejected/unknown分开；未提供原关系审核状态不能完成chunk或推进下一块，非目标审核3→4等进度单独观察，不撤销不变内容/顺序的证明，不推断信息分已刷新。无refresh只报告历史，不能当成新验证。

已有其他主视频不得覆盖；同一原视频的已存完全相同order1仅只读复用。卡/类目/标签/全SKU/本地身份确认或基线变化须停止，不能猜ID、缩SKU或换nonce重提。

每个chunk的attempt、原ack receipt和anchor独立不可覆盖，父批准原件也独立核验。倒退journal、删attempt/结果或丢journal但保留证明都不能重放。unknown保留原提交隔离，即使字段和关系匹配仍不会解锁，也不会继续下一chunk；已知提交但尚未读回可只读核对，再继续尚未尝试的chunk，不重发原chunk。

开发测试只用合成店铺、标签、卡、关系和本地媒体；实际上传/绑定、商家OAuth和商业视觉/声音验收未实测。签名URL和认证信息不会进入本绑定计划或业务回执。

写入要求原视频可用；只读回查允许报告后来的视频驳回，不能用写入就绪门槛遮蔽驳回状态。关系若提供jdVideoId则必须匹配；未提供该非必需字段时，仍以原视频查询的ID对、完整type42素材的相同ID对和关系精确videoId组合验证，不猜原生输出字段。原上传批准原件必需，但其旧deadline过期不要求重新上传。
