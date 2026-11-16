"""Task-owned, non-persistent browser; never exports cookies or private OAuth state."""
from __future__ import annotations

import hashlib
import json
import os

from .auth_flow import BrowserIdentityProof, eligible_identity_source, valid_oauth_url, JINGMAI_LOGIN_URL
from .safety import SafetyError

MAX_IDENTITY_BYTES = 1024 * 1024


class PlaywrightBrowser:
    def __init__(self, shop_name, vender_id=None, *, factory=None, headless=False, channel=None):
        self.tracker = BrowserIdentityProof(shop_name, vender_id)
        self.factory = factory
        self.headless = headless
        self.channel = channel
        self.controller = self.browser = self.context = self.page = None
        self.stage = "not-opened"
        self.pages = []
        self.identity_pages = {}
        self.untrusted_responses = self.non_json_responses = self.responses = 0

    def open_jingmai(self):
        if self.controller is not None:
            raise SafetyError("task-browser-already-opened")
        try:
            if self.factory is None:
                from playwright.sync_api import sync_playwright
                factory = sync_playwright
            else:
                factory = self.factory
            self.controller = factory().start()
            channels = [self.channel] if self.channel else (["msedge", "chrome"] if os.name == "nt" else ["chrome", "msedge"])
            for channel in channels:
                try:
                    self.browser = self.controller.chromium.launch(channel=channel, headless=self.headless)
                    break
                except Exception:
                    if channel == channels[-1]:
                        raise SafetyError("system-browser-unavailable-install-chrome-or-edge") from None
            self.context = self.browser.new_context(accept_downloads=False, service_workers="block")
            if hasattr(self.context,'on'):
                self.context.on('response',self._response)
                self.context.on('page',self._page_opened)
            self.page = self.context.new_page()
            self._page_opened(self.page)
            if not hasattr(self.context,'on'):self.page.on('response',self._response)
            self.stage = "jingmai-login"
            self.page.goto(JINGMAI_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            self.close()
            raise SafetyError("task-browser-unavailable") from None

    def _page_opened(self,page):
        if page not in self.pages:
            self.pages.append(page)
            page.on('framenavigated',lambda frame:self._page_navigated(page,frame))

    def _page_navigated(self,page,frame):
        if frame is getattr(page,'main_frame',None):
            self.identity_pages={key:value for key,value in self.identity_pages.items() if value is not page}

    def candidates(self):
        return [candidate for candidate in self.tracker.candidates()
                if (page:=self.identity_pages.get(candidate['fingerprint'])) is not None
                and page in self.pages and not page.is_closed()]

    def select_identity(self,proof):
        candidate=next((p for p in self.candidates() if p['fingerprint']==proof.get('fingerprint') and p['shopName']==proof.get('shopName') and p['venderId']==proof.get('venderId')),None)
        if candidate is None:raise SafetyError('live-task-identity-page-required')
        self.page=self.identity_pages[candidate['fingerprint']]

    def _response(self, response):
        if self.stage != "jingmai-login":
            return
        try:
            self.responses += 1
            if not eligible_identity_source(response.url):
                self.untrusted_responses += 1
                return
            if response.request.resource_type not in {'xhr','fetch'}:return
            if 'json' not in (response.header_value('content-type') or '').lower():
                self.non_json_responses += 1
                return
            page=response.frame.page if hasattr(response,'frame') else self.page
            if getattr(page,'context',self.context) is not self.context or page not in self.pages:return
            length = response.header_value("content-length")
            if length is not None:
                if not length.isdigit() or int(length) > MAX_IDENTITY_BYTES:
                    return
                payload = response.json()
            else:
                body = response.body()
                if len(body) > MAX_IDENTITY_BYTES:
                    return
                payload = json.loads(body)
            self.tracker.observe_json(response.url, payload)
            sha=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
            candidates=self.tracker.candidates()
            current_fingerprints={p['fingerprint'] for p in candidates}
            self.identity_pages={key:value for key,value in self.identity_pages.items() if key in current_fingerprints}
            for candidate in candidates:
                if candidate['responseSha256']==sha:self.identity_pages[candidate['fingerprint']]=page
            proof=self.proof()
            if proof:
                candidate=next((p for p in candidates if p['shopName']==proof['shopName'] and p['venderId']==proof['venderId']),None)
                if candidate:self.select_identity(candidate)
        except Exception:
            # Raw response or exception may contain credentials; neither is published.
            return

    def poll(self):
        if self.page is None or self.page.is_closed():
            self.page=next((p for p in reversed(self.pages) if not p.is_closed()),None)
        if self.page is None:raise SafetyError('task-browser-closed')
        self.page.wait_for_timeout(50)

    def proof(self):
        candidates=self.candidates()
        if len(candidates)!=1:return None
        candidate=candidates[0]
        if candidate['shopName']!=self.tracker.shop_name or (self.tracker.vender_id and candidate['venderId']!=self.tracker.vender_id):return None
        return {k:v for k,v in candidate.items() if k!='fingerprint'}

    def navigate_oauth(self, url):
        if not valid_oauth_url(url):
            raise SafetyError("official-oauth-url-required")
        if self.page is None or self.page.is_closed():
            raise SafetyError("task-browser-closed")
        self.stage = "official-oauth"
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            raise SafetyError("oauth-navigation-outcome-unknown") from None

    def public_observation(self):
        # Do not extract DOM, href, screenshots, request headers or storage state.
        summary=self.tracker.summary()
        candidates=self.candidates()
        summary.update(identityCandidateCount=len(candidates),matchingIdentityCount=sum(p['shopName']==self.tracker.shop_name and (not self.tracker.vender_id or p['venderId']==self.tracker.vender_id) for p in candidates),ambiguous=len(candidates)>1)
        diagnostic='identity-candidates-observed' if summary['identityCandidateCount'] else 'no-usable-shop-fields-in-json' if self.tracker.observed else 'no-eligible-json-response-yet'
        return {'browserStage':self.stage,'identity':self.proof(),**summary,'taskPageCount':sum(not p.is_closed() for p in self.pages),'observedResponseCount':self.responses,'untrustedResponseCount':self.untrusted_responses,'nonJsonResponseCount':self.non_json_responses,'identityDiagnostic':diagnostic,'privatePageContent':'not-exported','taskOwnedContext':True}

    def close(self):
        for resource in (self.context, self.browser):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        if self.controller is not None:
            try:
                self.controller.stop()
            except Exception:
                pass
        self.context = self.browser = self.page = self.controller = None
        self.pages=[];self.identity_pages={}
        self.stage = "closed"
