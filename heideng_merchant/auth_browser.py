"""Task-owned, non-persistent browser; never exports cookies or private OAuth state."""
from __future__ import annotations

import json
import os

from .auth_flow import BrowserIdentityProof, eligible_identity_source, valid_oauth_url
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
            self.page = self.context.new_page()
            self.page.on("response", self._response)
            self.stage = "jingmai-login"
            self.page.goto("https://jingmai.jd.com/", wait_until="domcontentloaded", timeout=30000)
        except Exception:
            self.close()
            raise SafetyError("task-browser-unavailable") from None

    def _response(self, response):
        if self.stage != "jingmai-login":
            return
        try:
            if not eligible_identity_source(response.url) or response.request.resource_type not in {"xhr", "fetch"}:
                return
            if "json" not in (response.header_value("content-type") or "").lower():
                return
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
        except Exception:
            # Raw response or exception may contain credentials; neither is published.
            return

    def poll(self):
        if self.page is None or self.page.is_closed():
            raise SafetyError("task-browser-closed")
        self.page.wait_for_timeout(50)

    def proof(self):
        return self.tracker.proof()

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
        return {"browserStage": self.stage, "identity": self.tracker.proof(), **self.tracker.summary(),
                "privatePageContent": "not-exported", "taskOwnedContext": True}

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
        self.stage = "closed"
