# 分发说明

维护者已确认保留公开研发仓库，并允许推送商家内测代码。每个第三方组件沿用其原许可证、注明的来源与分发授权；本说明不扩大第三方授权范围。定向免费内测、公开市场上架及未来收费发行分别安排。商家凭据、内测资格名册和运行数据留在其授权环境。官方 CLI 及其他第三方资源由用户按原条款从原来源取得。

## 复用的 LTS4AI 客户端

`heideng_merchant/lts4ai_client.py` 复用 ctzlyj/sufy-image2 的 MIT 客户端核心，来源 commit `b2b5724d77787b49469f43308f9e1de57438ee08`，完整原文件 SHA256 `24a38c11f267924352d3ecfbe0b3fcbe33adf54ff0b211d0648e3fa1d4ac51ef`。未复制其独立CLI与个人凭据查找；商家包装禁用提交重试和重定向，固定用户选择的网关与模型。以下保留上游许可全文：

MIT License

Copyright (c) 2026 CTctikki

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## 本轮已明确许可的成熟业务源码

- `mature/listing`：ctzlyj/jingmai-hot-product-mover-skill，1.2.6 / 3ee08af2f3970f88d39756f1906040efe75117dc。
- `mature/collection`：ctzlyj/jd-hot-link-collector，1.0.4 / 90ef8dfd8455848d539d22560ae26ba8bac52e2a。
- `mature/comparison`：ctzlyj/jd-competitor-price-adjustment-skill，1.0.0 / 43bdf6790fe3c8a5b89c217edcaefabf670cbc2c。

三者均保留各自 `LICENSE` 原文、来源、原文件 SHA 与商家适配 SHA，见各 `provenance.json`。只选择必要 Git 跟踪源码和模板，不包含作者运行目录。原源码与薄适配文件明确区分，不把新增接口层说成成熟业务源文件。

连接器、POP 素材、整店图片刷新、诊断和视频本地交接代码按用户确认的私有商家分发范围选择性迁入；各自保留 DISTRIBUTION-PERMISSION.md，不把缺少上游公开许可证说成 MIT，也不因此重写业务。
新增本地交接源：ctzlyj/jd-main-video-batch-skill 1.1.3 / 40d664e98d173cf0e6387f4c3f387cab504b3e43，仅 video_publication.py/check_main_video.py，不包括公司模型/视频生成器。
实际诊断源为 ctzlyj/jd-store-diagnosis-skill 0.2.0 / 42971c041248bab27f4d627357dcc475f848eb75；原 L1/L2，排除员工 L3。

本版本不创建公开 Release，不改变商家仓库或上游仓库可见性，不主动通知商家。原成熟平台规则/素材版权要求仍然有效。


Owner-confirmed private merchant distribution (2026-11-16): necessary pure business code/templates
from ctzlyj/jingmai-cli-linker (1.0.2 / 1c438fc5419cd86f709cc4a501325782fd4a1e36)
and ctzlyj/jd-material-pop-skill (nested 2026.11.207 / b56b22376db88182352d3f64ea3e9752d4ae5677)
are selectively included. These upstream snapshots have no explicit LICENSE; their included
DISTRIBUTION-PERMISSION.md files describe the user-confirmed scope, not MIT or public relicensing.
No runtime credentials/browser profiles/model weights are distributed. Third-party cutout model
sources remain separately attributed in the original metadata; only fixed SHA allowlists, no weights.
