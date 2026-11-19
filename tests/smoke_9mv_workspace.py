"""Real Playwright API against intercepted synthetic pages, not merchant login."""
import sys,tempfile,json,os
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from heideng_merchant.host_connection_controller import HostConnectionController

with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}),sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    closed=False
    try:
        context=browser.new_context()
        seen=[]
        def intercept(route):
            url=route.request.url;seen.append(url)
            if url.startswith('https://passport.shop.jd.com/'):
                route.fulfill(status=200,content_type='text/html',body='<body>密码登录 店铺 客服</body>')
            elif url.startswith('https://shop.jd.com/'):
                route.fulfill(status=200,content_type='text/html',body='<body>店铺 客服<div class="shop-menu-accountV1__right-account-top-name">fixture-shop</div></body>')
            else:route.abort()
        context.route('**/*',intercept)
        login=context.new_page();login.goto('https://passport.shop.jd.com/login/index.action')
        controller=HostConnectionController(state=d,shop_identity={'shopName':'fixture-shop'})
        controller.context=context;controller.page=login;controller.context_id='fixture';controller.channel='msedge';controller.profile=Path(d)/'browser-profiles/fixture'
        observation=controller._observe()
        assert observation['loggedIn'] and observation['identity']=={'shopName':'fixture-shop'}
        assert login.url.startswith('https://passport.shop.jd.com/')
        assert controller.page.url.startswith('https://shop.jd.com/')
        assert set(seen)=={'https://passport.shop.jd.com/login/index.action','https://shop.jd.com/jdm/home'}
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mature/connection/app'))
        from browser_adapters import BuiltinBrowser
        from heideng_merchant import host_connection_controller as hc
        controller._playwright=p
        with patch.object(hc,'HostConnectionController',return_value=controller):adapter=BuiltinBrowser({'shopName':'fixture-shop'})
        assert adapter.observe()['loggedIn']
        assert adapter.close()['status']=='closed';closed=True
        print(json.dumps({'status':'synthetic-workspace-observed','realPlaywright':True,'builtinCloseVerified':True,'realMerchantLogin':False,'requestsIntercepted':len(seen),'externalRequestsSent':0}))
    finally:
        if not closed:browser.close()
