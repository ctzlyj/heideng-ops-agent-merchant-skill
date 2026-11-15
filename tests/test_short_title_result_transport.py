import importlib
import unittest
from tests.short_title_result_fixtures import TransportFactory
from heideng_merchant.safety import SafetyError

URL = "https://storage.jd.com/synthetic/result.xlsx?token=synthetic-only-private"


class ShortTitleResultTransportTests(unittest.TestCase):
    def make(self, raw=b"synthetic-result"):
        wire = TransportFactory(raw)
        cls = importlib.import_module("heideng_merchant.short_title_result_transport").ResultTransport
        return wire, cls(resolver=wire.resolver, connection_factory=wire, clock=lambda: 1000)

    def test_exact_get_original_bytes_no_auth_headers_and_no_retries(self):
        wire, transport = self.make()
        raw, proof = transport.fetch(URL, deadline=1060)
        self.assertEqual(raw, b"synthetic-result")
        self.assertEqual(proof["byteCount"], len(raw))
        self.assertEqual(len(wire.requests), 1)
        self.assertEqual(wire.requests[0][0], "GET")
        self.assertNotIn("Authorization", wire.requests[0][2])
        self.assertNotIn("Cookie", wire.requests[0][2])
        self.assertEqual(wire.requests[0][2]["Accept-Encoding"], "identity")
        self.assertEqual(wire.debuglevel, 0)
        self.assertTrue(wire.connection.closed)
        self.assertNotIn("synthetic-only-private", str(proof))

    def test_nonpublic_mixed_or_unlisted_target_is_refused_before_get(self):
        wire, transport = self.make()
        wire.ips = ["93.184.216.34", "127.0.0.1"]
        with self.assertRaises(SafetyError):
            transport.fetch(URL, deadline=1060)
        self.assertFalse(wire.requests)
        for url in ("http://storage.jd.com/synthetic/result.xlsx", "https://example.invalid/result.xlsx", "https://user:synthetic@storage.jd.com/result", "https://storage.jd.com:444/result", "https://storage.jd.com./result"):
            with self.subTest(url=url.split("/")[2]), self.assertRaises(SafetyError):
                transport.fetch(url, deadline=1060)
        self.assertFalse(wire.requests)

    def test_redirect_bad_mime_or_compression_not_followed_or_decoded(self):
        for scenario in ("redirect", "mime", "gzip"):
            with self.subTest(scenario=scenario):
                wire, transport = self.make()
                if scenario == "redirect":
                    wire.response.status = 302
                    wire.response.headers.append(("Location", "https://example.invalid/synthetic"))
                elif scenario == "mime":
                    wire.response.headers[0] = ("Content-Type", "application/json")
                else:
                    wire.response.headers.append(("Content-Encoding", "gzip"))
                with self.assertRaises(SafetyError):
                    transport.fetch(URL, deadline=1060)
                self.assertEqual(len(wire.requests), 1)
                self.assertTrue(wire.connection.closed)

    def test_duplicate_conflicting_headers_and_truncated_length_refused(self):
        for headers in (("Content-Length", "999"), ("Content-Type", "application/json"), ("Content-Encoding", "identity")):
            with self.subTest(header=headers[0]):
                wire, transport = self.make()
                if headers[0] == "Content-Encoding":
                    wire.response.headers.extend([headers, headers])
                else:
                    wire.response.headers.append(headers)
                with self.assertRaises(SafetyError):
                    transport.fetch(URL, deadline=1060)
        wire, transport = self.make()
        wire.response.headers[1] = ("Content-Length", "99")
        with self.assertRaises(SafetyError):
            transport.fetch(URL, deadline=1060)

    def test_empty_and_over_byte_limit_refused_with_bounded_reads(self):
        for raw in (b"", b"x" * (5 * 1024 * 1024 + 1)):
            with self.subTest(size=len(raw)):
                wire, transport = self.make(raw)
                wire.response.headers = [wire.response.headers[0]]
                with self.assertRaises(SafetyError):
                    transport.fetch(URL, deadline=1060)
                self.assertLessEqual(wire.response.offset, 5 * 1024 * 1024 + 1)

    def test_expired_or_nonfinite_deadline_never_dispatches(self):
        wire, transport = self.make()
        for deadline in (1000, True, float("inf"), float("nan")):
            with self.subTest(deadline=str(deadline)), self.assertRaises(SafetyError):
                transport.fetch(URL, deadline=deadline)
        self.assertFalse(wire.requests)

    def test_raw_error_echo_is_not_returned(self):
        wire, transport = self.make()
        wire.error = True
        with self.assertRaises(SafetyError) as caught:
            transport.fetch(URL, deadline=1060)
        self.assertNotIn("synthetic-only-private", str(caught.exception))
        self.assertEqual(len(wire.requests), 1)
        self.assertTrue(wire.connection.closed)


if __name__ == "__main__":
    unittest.main()
