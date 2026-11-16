"""New synthetic fixture server; only two exact routes, no directory access."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os

BODY = Path(__file__).with_name('index.html').read_bytes()
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        if self.path == '/favicon.ico':
            self.send_response(204); self.end_headers(); return
        if self.path not in ('/', '/index.html'):
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self'; connect-src 'none'; form-action 'none'")
        self.send_header('Content-Length', str(len(BODY)))
        self.end_headers(); self.wfile.write(BODY)

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
print(json.dumps({'url': 'http://127.0.0.1:%d/' % server.server_port, 'pid': os.getpid(), 'synthetic': True}), flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
