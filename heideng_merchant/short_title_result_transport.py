"""Bounded GET of one observed public result URL; no cookies, redirects or retries."""
import hashlib
import http.client
import ipaddress
import math
import socket
import ssl
import time
from urllib.parse import urlsplit

from .safety import SafetyError
from .short_title_browser_contract import source_url
from .short_title_import_contract import object_sha

MAX_BYTES = 5 * 1024 * 1024
MIMES = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream"}


class ResultTransport:
    def __init__(self, *, resolver=None, connection_factory=None, clock=None):
        self.resolver = resolver or socket.getaddrinfo
        self.connection_factory = connection_factory or http.client.HTTPSConnection
        self.clock = clock or time.time

    def fetch(self, url, *, deadline):
        connection = None
        def remaining():
            now = self.clock()
            if type(deadline) not in (int, float) or not math.isfinite(deadline) or type(now) not in (int, float) or not math.isfinite(now) or not 0 < deadline - now <= 120:
                raise SafetyError("bounded-original-result-download-deadline-required")
            timeout = min(30, deadline - now)
            if connection is not None:
                connection.timeout = timeout
                if getattr(connection, "sock", None) is not None:
                    connection.sock.settimeout(timeout)
            return timeout
        try:
            remaining()
            if not source_url(url, template=True) or any(ord(char) > 126 for char in url):
                raise SafetyError("observed-public-result-url-required")
            target = urlsplit(url)
            host = target.hostname
            addresses = self.resolver(host, 443, type=socket.SOCK_STREAM)
            ips = [row[4][0] for row in addresses]
            if not ips or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast or ipaddress.ip_address(ip).is_reserved for ip in ips):
                raise SafetyError("public-result-dns-required")
            connection = self.connection_factory(host, 443, timeout=remaining(), context=ssl.create_default_context())
            # Resolve once, keep TLS/SNI bound to the observed hostname.
            connection._create_connection = lambda address, timeout=None, source_address=None: socket.create_connection((ips[0], 443), timeout=timeout, source_address=source_address)
            if callable(getattr(connection, "set_debuglevel", None)):
                connection.set_debuglevel(0)
            path = (target.path or "/") + ("?" + target.query if target.query else "")
            remaining()
            connection.request("GET", path, headers={"Accept": ", ".join(sorted(MIMES)), "Accept-Encoding": "identity"})
            remaining()
            response = connection.getresponse()
            if response.status != 200:
                raise SafetyError("successful-original-result-get-required")
            headers = {}
            for key, value in response.getheaders():
                name = key.lower()
                if name in ("content-type", "content-length", "content-encoding"):
                    if name in headers or not isinstance(value, str):
                        raise SafetyError("unambiguous-result-response-headers-required")
                    headers[name] = value
            mime = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            size = headers.get("content-length")
            if mime not in MIMES or headers.get("content-encoding", "identity").lower() != "identity":
                raise SafetyError("original-xlsx-result-response-required")
            if size is not None and (not size.isascii() or not size.isdigit() or not 0 < int(size) <= MAX_BYTES):
                raise SafetyError("bounded-result-response-size-required")
            raw = bytearray()
            while len(raw) <= MAX_BYTES:
                remaining()
                chunk = response.read(min(65536, MAX_BYTES + 1 - len(raw)))
                if not isinstance(chunk, bytes):
                    raise SafetyError("original-result-byte-stream-required")
                if not chunk:
                    break
                raw.extend(chunk)
            remaining()
            if not 0 < len(raw) <= MAX_BYTES or size is not None and len(raw) != int(size):
                raise SafetyError("complete-bounded-original-result-required")
            body = bytes(raw)
            return body, {"resultObjectSha256": object_sha(url), "resultFileSha256": hashlib.sha256(body).hexdigest(), "byteCount": len(body), "contentType": mime}
        except Exception:
            raise SafetyError("original-title-result-download-not-verified") from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
