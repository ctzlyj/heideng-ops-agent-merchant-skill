# 商品素材与到手价采集

使用当前宿主可用浏览器工具，不默认依赖公司WebCLI/O2插件。保持工作浏览器不受干扰；新任务使用任务专属tab/context，已有会话仅在目标与权限已核对时复用。

先观察商品原生前台的选中SKU和SKU顺序，必要时调用已观察到且当前账号合法可访问的页面接口；不猜接口、不绕过风控/验证码或复制Cookie。每个SKU记录实际规格、选中状态和真实到手价来源；不拿搜索页统一价格填所有SKU。

snapshot结构：title、真实canonical商品url、selectedSkuId、skuOrder、skus（每SKU实际handPrice与priceEvidence=native-sku-context）、assets（当前可访问的真实图片/视频url与kind/skuId）。字段标记必须由观察证据支撑，不是为了通过校验而补。

package-snapshot严格核对SKU集合与原生顺序，按顺序写skus.csv、商品JSON和素材文件hash。默认仅下载明确公开JD CDN资源、不附鉴权。带签名/复杂查询/登录才能取的资源由宿主在原会话下载到任务目录，再扩展本地素材交接；不得复制签名/Token进源码或输出。下载失败不造文件、不跨平台重复提交。

采集与上架分离；采集不带店铺写入批准。第三方图片使用/复刻权利需另外核对。
