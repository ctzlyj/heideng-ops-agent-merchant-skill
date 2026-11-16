"""Real local HTTP wire/decode; no request reaches LTS4AI and no paid call."""
import base64, io, json, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tempfile import TemporaryDirectory
from pathlib import Path
from PIL import Image
from heideng_merchant.mature_image import MerchantImageClient

class ImageBoundaryTests(unittest.TestCase):
    def wire(self, response_code=200, error_message="synthetic upstream failure"):
        requests = []
        payload = io.BytesIO()
        Image.new('RGB', (32, 32), 'red').save(payload, 'PNG')
        response = json.dumps({'data':[{'b64_json':base64.b64encode(payload.getvalue()).decode()}]}).encode()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                requests.append((self.path, self.headers['Content-Type'], body))
                self.send_response(response_code)
                self.send_header('Content-Type','application/json')
                self.end_headers()
                self.wfile.write(response if response_code==200 else json.dumps({'error':{'message':error_message}}).encode())
        server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        client = MerchantImageClient('synthetic-merchant-marker')
        self.assertEqual(client.client.api_root, 'https://api.lts4ai.com/v1')
        # Deliberate test-only local route. Production does not expose an endpoint switch.
        client.client.api_root = 'http://127.0.0.1:'+str(server.server_port)+'/v1'
        return client, requests

    def test_real_generation_uses_sufy_protocol_and_returns_jpeg(self):
        client, requests = self.wire()
        output = client.edit(prompt='synthetic product', images=[])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][0], '/v1/images/generations')
        body = json.loads(requests[0][2])
        self.assertEqual(body['model'], 'gpt-image-2.5')
        self.assertEqual(set(body), {'model','prompt','size','output_format'})
        with Image.open(io.BytesIO(output)) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.size, (32, 32))

    def test_reference_edit_uses_existing_multipart_contract(self):
        client, requests = self.wire()
        with TemporaryDirectory() as d:
            source = Path(d)/'photo.png'
            Image.new('RGB',(32,32),'blue').save(source)
            client.edit(prompt='keep exact product', images=[source])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][0], '/v1/images/edits')
        self.assertTrue(requests[0][1].startswith('multipart/form-data; boundary='))
        self.assertIn(b'gpt-image-2.5', requests[0][2])
        self.assertIn(b'name="image"', requests[0][2])

    def test_quota_response_cannot_echo_merchant_key(self):
        client, requests = self.wire(403, 'quota exhausted for synthetic-merchant-marker')
        with self.assertRaises(Exception) as failure:
            client.edit(prompt='synthetic product', images=[])
        self.assertEqual(len(requests), 1)
        self.assertNotIn('synthetic-merchant-marker', str(failure.exception))

    def test_upstream_unknown_result_is_not_resubmitted(self):
        client, requests = self.wire(500)
        with self.assertRaises(Exception) as failure:
            client.edit(prompt='synthetic product', images=[])
        self.assertEqual(len(requests), 1)
        self.assertNotIn('synthetic-merchant-marker', str(failure.exception))

if __name__=='__main__': unittest.main()
