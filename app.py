"""Local-only server. Run: python3 app.py"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from core import ROOT, AppError, load_env, load_patients, select_patient, generate_answer

load_env()
PATIENTS = load_patients()
STATIC = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8')}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Do not log patient questions or credentials.

    def reply(self, status, body, mime='application/json; charset=utf-8'):
        data = json.dumps(body).encode() if mime.startswith('application/json') else body
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') not in {expected, f'localhost:{self.server.server_port}'}:
            self.reply(403, {'error': 'Use the localhost URL printed by the server.'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://{expected}', f'http://localhost:{self.server.server_port}'}:
            self.reply(403, {'error': 'Cross-origin requests are not allowed.'})
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        url = urlparse(self.path)
        if url.path in STATIC:
            filename, mime = STATIC[url.path]
            return self.reply(200, (ROOT / 'static' / filename).read_bytes(), mime)
        if url.path == '/api/status':
            key = os.environ.get('OPENAI_API_KEY', '').strip()
            return self.reply(200, {'configured': bool(key and key not in {'your_openai_api_key_here', 'replace_me'}),
                                    'model': os.environ.get('OPENAI_MODEL', 'gpt-4.1-mini'), 'patient_count': len(PATIENTS)})
        if url.path == '/api/patients':
            return self.reply(200, [{'patient_id': p['patient_id'], 'name': p['name']} for p in PATIENTS])
        if url.path == '/api/patient':
            try:
                return self.reply(200, select_patient(PATIENTS, parse_qs(url.query).get('id', [''])[0]))
            except AppError as error:
                return self.reply(404, {'error': str(error)})
        self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.local_request():
            return
        if self.path != '/api/generate':
            return self.reply(404, {'error': 'Not found'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(415, {'error': 'Use application/json.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 12000:
                return self.reply(413, {'error': 'Invalid request size.'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError()
            patient = select_patient(PATIENTS, body.get('patient_id'))
            return self.reply(200, generate_answer(patient, body.get('question')))
        except (ValueError, UnicodeError):
            self.reply(400, {'error': 'Invalid JSON request.'})
        except AppError as error:
            self.reply(400, {'error': str(error)})
        except Exception:
            self.reply(500, {'error': 'Unexpected server error. Restart the application.'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'SlashDr synthetic-data demo: http://127.0.0.1:{port}')
    print('Press Ctrl+C to stop. API key is never sent to the browser.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
