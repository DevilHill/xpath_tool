"""仅提供可视化编辑器的浏览器预览，实际执行在 VS Code 中完成。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=8797)
args = parser.parse_args()
media = Path(__file__).resolve().parents[1] / 'media'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/', '/index.html'):
            content = (media / 'flow-editor.html').read_text(encoding='utf-8')
            content = content.replace('__CSP_SOURCE__', "'self'").replace('__NONCE__', 'localpreview')
            for name in ('flow-editor.css', 'flow-model.js', 'flow-editor.js'):
                content = content.replace('__'+name+'__', '/'+name)
            data, mime = content.encode('utf-8'), 'text/html; charset=utf-8'
        elif self.path in ('/flow-editor.css', '/flow-model.js', '/flow-editor.js'):
            data = (media / self.path[1:]).read_bytes()
            mime = 'text/css' if self.path.endswith('.css') else 'application/javascript'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


print(f'编辑器预览：http://127.0.0.1:{args.port}', flush=True)
ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
