# 分发说明

当前为私有研发交付，尚未授予公开源代码分发或商业收费许可。不得打包无许可证内部源码、员工配置、凭据、运行数据或未知资源。官方CLI和其他第三方资源由用户在其授权条款下从原来源获取，本项目不替其重授许可。生图已指定LTS4AI / gpt-image-2.5；视频生成服务尚待选择。

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
