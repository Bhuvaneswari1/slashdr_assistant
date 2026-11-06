"""FastAPI route checks without a network port or extra test dependencies."""
import asyncio
import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api


async def asgi_request(path, method='GET', body=None, headers=None):
    sent = []
    delivered = False
    encoded = b'' if body is None else json.dumps(body).encode()
    path, _, query = path.partition('?')
    scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
             'http_version': '1.1', 'method': method, 'scheme': 'http',
             'path': path, 'raw_path': path.encode(), 'query_string': query.encode(),
             'root_path': '', 'server': ('testserver', 80), 'client': ('127.0.0.1', 12345),
             'headers': [(b'host', b'testserver'), (b'content-type', b'application/json')]
                        + [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]}

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {'type': 'http.request', 'body': encoded, 'more_body': False}
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    await api.app(scope, receive, send)
    start = next(m for m in sent if m['type'] == 'http.response.start')
    payload = b''.join(m.get('body', b'') for m in sent if m['type'] == 'http.response.body')
    return start['status'], payload, dict(start['headers'])


class FastAPITests(unittest.TestCase):
    def setUp(self):
        self.mode_patch = patch.dict('os.environ', {'DATA_MODE': 'synthetic', 'REVIEW_ACCOUNTS_JSON': ''})
        self.mode_patch.start()
        self.addCleanup(self.mode_patch.stop)
        self.auth_patch = patch.multiple(api, REVIEW_USERNAME='', REVIEW_PASSWORD='')
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)

    def request(self, *args, **kwargs):
        return asyncio.run(asgi_request(*args, **kwargs))

    def test_swagger_and_openapi(self):
        status, body, _ = self.request('/docs')
        self.assertEqual(status, 200)
        self.assertIn(b'SwaggerUIBundle', body)
        status, body, _ = self.request('/openapi.json')
        self.assertEqual(status, 200)
        spec = json.loads(body)
        self.assertIn('/api/generate', spec['paths'])
        self.assertIn('requestBody', spec['paths']['/api/generate']['post'])

    def test_ui_assets_and_patients(self):
        for path in ['/', '/app.js', '/style.css', '/health', '/api/status']:
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 200)
        status, body, _ = self.request('/api/patients')
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)), 100)
        status, body, _ = self.request('/api/patient?id=P010')
        self.assertEqual(json.loads(body)['patient_id'], 'P010')

    def test_generation_preserves_ui_response(self):
        answer = {'patient_id': 'P010', 'answer': 'Routine review [P010-PROFILE].',
                  'source_ids': ['P010-PROFILE'], 'missing_information': []}
        with patch('api.generate_answer', return_value=answer) as generate:
            status, body, _ = self.request('/api/generate', 'POST', {'patient_id': 'P010', 'question': 'Summary'})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), answer)
            self.assertEqual(generate.call_args.args[0]['patient_id'], 'P010')

    def test_request_validation_and_unknown_patient(self):
        for body in [{'patient_id': 'P010', 'question': ''},
                     {'patient_id': 'P010', 'question': 'x' * 2001},
                     {'patient_id': 'wrong', 'question': 'Summary'}]:
            with self.subTest(body=str(body)[:50]):
                status, result, _ = self.request('/api/generate', 'POST', body)
                self.assertEqual(status, 422)
                self.assertIn('error', json.loads(result))
        self.assertEqual(self.request('/api/patient?id=P999')[0], 404)

    def test_source_error_format(self):
        with patch('api.generate_answer', side_effect=api.AppError('Source validation failed: unknown record.')):
            status, body, _ = self.request('/api/generate', 'POST', {'patient_id': 'P010', 'question': 'Summary'})
            self.assertEqual(status, 400)
            self.assertIn('Source validation', json.loads(body)['error'])

    def test_private_files_not_served_and_cross_origin_rejected(self):
        for path in ['/.env', '/.env.example', '/core.py', '/data/patients.json']:
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request('/api/patients', headers={'Origin': 'https://example.com'})[0], 403)

    def test_reviewer_login_covers_docs_ui_and_api(self):
        with patch.multiple(api, REVIEW_USERNAME='reviewer', REVIEW_PASSWORD='test-only-password'):
            for path in ['/', '/docs', '/openapi.json', '/api/patients']:
                status, body, headers = self.request(path)
                self.assertEqual(status, 401)
                self.assertIn(b'www-authenticate', headers)
            self.assertEqual(self.request('/health')[0], 200)
            token = base64.b64encode(b'reviewer:test-only-password').decode()
            self.assertEqual(self.request('/docs', headers={'Authorization': f'Basic {token}'})[0], 200)
            self.assertEqual(self.request('/docs', headers={'Authorization': 'Basic invalid!'})[0], 401)


if __name__ == '__main__':
    unittest.main()
