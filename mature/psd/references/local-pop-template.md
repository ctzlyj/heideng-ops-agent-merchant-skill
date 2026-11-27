# POP 本地分层打标模板

宿主从商家自有的 800×800 PNG、活动目标及已确认的字段映射制作模板。原图中的固定装饰保留为像素，确认需要替换的文案和自动价格使用可编辑文字层。已有价格口径、映射和本次任务授权可以沿用；新的价格规则或素材范围才需核实。

使用业务入口 `scripts/psd_template.cjs`。商家入口为 `run psd-template --`，后接相同参数。

- `status` 查看本机可选运行时，尚未调用制作时无需安装依赖。
- `build --source <原图.png> --spec <字段.json> --output-dir <新目录>` 交付 PSD、预览、来源图、template.json 和 validation.json。首次使用按包内 npm 锁文件准备本地环境，也可用 `prepare` 提前准备。
- `verify --manifest <template.json>` 重新打开 PSD 核对图层类型、位置、文字层索引、自动价格、Excel 映射及文件 SHA256。上传由宿主按单独的目标和店铺授权处理。

字段示例中的坐标使用原图像素，实际坐标、文案及映射由宿主根据当前素材提供。自动价格映射到京东价格字段，Excel 文案列从 `文案1` 顺序编号；没有自动价格需求可省略 `automaticPriceLayer`。

```json
{
  "schemaVersion": 1,
  "templateId": "campaign-label",
  "displayName": "活动打标",
  "dynamicFields": [{
    "jdColumn": "文案1",
    "businessRole": "campaign",
    "bounds": [20, 620, 300, 665],
    "sampleText": "活动主题",
    "font": {"name": "ArialMT", "fontSize": 28, "color": [20, 20, 20]}
  }],
  "automaticPriceLayer": {
    "bounds": [410, 640, 680, 702],
    "sampleText": "19.90",
    "font": {"name": "ArialMT", "fontSize": 32, "color": [20, 20, 20]}
  }
}
```

`localStatus=passed` 表示本地结构校验通过，`jdUploadStatus=pending` 表示尚无平台上传验收。需要京东兼容文字引擎时可明确传 `--official-engine <已授权本地文件>`；没有引擎时仍交付可核验的本地分层 PSD，并报告 `jdReady=false`。此入口不调用生图或付费模型。
