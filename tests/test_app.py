import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core
import app
from generate_data import generate


def response(answer='Recorded BP is 125/76 mmHg [P001-V3].', sources=None):
    body = {'answer': answer, 'source_ids': ['P001-V3'] if sources is None else sources, 'missing_information': []}
    return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(body)}]}]}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.patients = core.load_patients()
        self.patient = self.patients[0]

    def test_exactly_100_patients_and_three_encounters(self):
        self.assertEqual(self.patients, generate())
        self.assertEqual(len(self.patients), 100)
        self.assertEqual(len({p['patient_id'] for p in self.patients}), 100)
        ids = [r['record_id'] for p in self.patients for r in p['records']]
        self.assertEqual(len(ids), len(set(ids)))
        for patient in self.patients:
            self.assertTrue(patient['synthetic'])
            self.assertEqual(sum(r['type'] == 'vitals' for r in patient['records']), 3)

    def test_missing_allergy_is_not_no_allergy(self):
        profile = self.patients[3]['records'][0]
        self.assertEqual(profile['allergy_status'], 'Not documented')
        self.assertEqual(profile['allergies'], [])

    def test_patient_context_isolation(self):
        payload = core.build_payload(self.patient, 'Summarise', 'test-model')
        context = json.loads(payload['input'])
        self.assertEqual(context['selected_patient_id'], 'P001')
        self.assertTrue(all(r['record_id'].startswith('P001-') for r in context['records']))
        self.assertNotIn('P002', payload['input'])
        self.assertFalse(payload['store'])
        self.assertTrue(payload['text']['format']['strict'])

    def test_unknown_patient(self):
        with self.assertRaises(core.AppError):
            core.select_patient(self.patients, 'P999')

    def test_response_and_citations(self):
        result = core.parse_response(response(), self.patient)
        self.assertEqual(result['patient_id'], 'P001')
        self.assertEqual(result['source_ids'], ['P001-V3'])

    def test_cross_patient_reference_is_rejected(self):
        with self.assertRaises(core.AppError):
            core.parse_response(response('Something [P002-V3].', ['P002-V3']), self.patient)

    def test_valid_inline_list_mismatch_is_reconciled(self):
        result = core.parse_response(response('Something [P001-V1].'), self.patient)
        self.assertEqual(result['source_ids'], ['P001-V1'])

    def test_grouped_citations_are_normalized(self):
        for separator in [', ', '; ', ' | ', ' & ', ' and ']:
            with self.subTest(separator=separator):
                result = core.parse_response(response(f'Readings [P001-V1{separator}P001-V2].', ['P001-V1', 'P001-V2']), self.patient)
                self.assertEqual(result['answer'], 'Readings [P001-V1] [P001-V2].')
                self.assertEqual(result['source_ids'], ['P001-V1', 'P001-V2'])

    def test_p010_summary_regression(self):
        patient = core.select_patient(self.patients, 'P010')
        result = core.parse_response(response('Routine review [P010-PROFILE, P010-N3].', ['P010-PROFILE']), patient)
        self.assertEqual(result['source_ids'], ['P010-PROFILE', 'P010-N3'])
        self.assertEqual(result['patient_id'], 'P010')

    def test_whitespace_backticks_and_duplicates(self):
        result = core.parse_response(response('Readings [ `P001-V1` ; P001-V1 ] [ P001-V2 ].', [' P001-V1 ', 'P001-V2']), self.patient)
        self.assertEqual(result['answer'], 'Readings [P001-V1] [P001-V2].')
        self.assertEqual(result['source_ids'], ['P001-V1', 'P001-V2'])

    def test_empty_metadata_rebuilt_from_valid_inline_citations(self):
        result = core.parse_response(response('Reading [P001-V1].', []), self.patient)
        self.assertEqual(result['source_ids'], ['P001-V1'])

    def test_unknown_and_malformed_citations_still_rejected(self):
        for citation in ['[P001-UNKNOWN]', '[P001-V1, P002-V1]', '[P001-V1, bogus]',
                         '[P001-V1, ]', '[P001-V1', '[[P001-V1]]', '[P001-V1–P001-V3]']:
            with self.subTest(citation=citation), self.assertRaises(core.AppError):
                core.parse_response(response('Reading ' + citation, []), self.patient)

    def test_unknown_list_id_is_not_silently_removed(self):
        with self.assertRaisesRegex(core.AppError, 'source list'):
            core.parse_response(response('Reading [P001-V1].', ['P002-V1']), self.patient)

    def test_valid_source_list_without_inline_citations_is_preserved(self):
        result = core.parse_response(response('Reading is available.', ['P001-V1']), self.patient)
        self.assertEqual(result['answer'], 'Reading is available.')
        self.assertEqual(result['source_ids'], ['P001-V1'])

    def test_schema_restricts_sources_to_selected_patient_without_mutation(self):
        first = core.build_payload(self.patient, 'Summary', 'test-model')
        second = core.build_payload(self.patients[9], 'Summary', 'test-model')
        def ids(payload):
            return payload['text']['format']['schema']['properties']['source_ids']['items']['enum']
        self.assertTrue(all(x.startswith('P001-') for x in ids(first)))
        self.assertTrue(all(x.startswith('P010-') for x in ids(second)))
        self.assertNotIn('enum', core.SCHEMA['properties']['source_ids']['items'])

    def test_missing_evidence_can_have_no_sources(self):
        result = core.parse_response(response('No result is documented.', []), self.patient)
        self.assertEqual(result['source_ids'], [])

    def test_refusal_incomplete_and_malformed(self):
        bad = [ {'status': 'incomplete'},
                {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal'}]}]},
                {'status': 'completed', 'output': []} ]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(core.AppError):
                core.parse_response(item, self.patient)

    def test_key_required_and_question_limits(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'your_openai_api_key_here'}):
            for question in ['Summarise', '', None, 'a' * 2001]:
                with self.subTest(question=str(question)[:10]), self.assertRaises(core.AppError):
                    core.generate_answer(self.patient, question)

    def test_actual_http_request_shape_with_mock_transport(self):
        def opener(request, timeout):
            self.assertEqual(timeout, 60)
            self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-only')
            payload = json.loads(request.data)
            self.assertEqual(json.loads(payload['input'])['selected_patient_id'], 'P001')
            return io.BytesIO(json.dumps(response()).encode())
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}):
            self.assertEqual(core.generate_answer(self.patient, 'Show BP', opener)['source_ids'], ['P001-V3'])

    def test_http_errors_are_redacted(self):
        def opener(*args, **kwargs):
            raise urllib.error.HTTPError('https://api.openai.com', 401, 'secret error body', {}, None)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}):
            with self.assertRaisesRegex(core.AppError, 'API key was rejected'):
                core.generate_answer(self.patient, 'Show BP', opener)

    def test_env_loading_preserves_existing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('TEST_SLASHDR_CONFIG="from-file"\n')
            with patch.dict(os.environ, {'TEST_SLASHDR_CONFIG': 'existing'}):
                core.load_env(path)
                self.assertEqual(os.environ['TEST_SLASHDR_CONFIG'], 'existing')


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_ui_assets_and_api(self):
        for path in ['/', '/style.css', '/app.js', '/api/patients', '/api/patient?id=P001', '/api/status']:
            with self.subTest(path=path), urllib.request.urlopen(self.base + path) as reply:
                self.assertEqual(reply.status, 200)
                body = reply.read()
                self.assertNotIn(b'your_openai_api_key_here', body)
        with urllib.request.urlopen(self.base + '/api/patients') as reply:
            self.assertEqual(len(json.load(reply)), 100)

    def test_env_not_served(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + '/.env')
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()

    def test_cross_origin_post_rejected(self):
        request = urllib.request.Request(self.base + '/api/generate', data=b'{}',
            headers={'Content-Type': 'application/json', 'Origin': 'https://example.org'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_generation_route_end_to_end_with_mock_api(self):
        with patch('app.generate_answer', return_value={'patient_id': 'P001', 'answer': 'Demo', 'source_ids': [], 'missing_information': []}) as mocked:
            request = urllib.request.Request(self.base + '/api/generate',
                data=json.dumps({'patient_id': 'P001', 'question': 'Summarise'}).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request) as reply:
                self.assertEqual(json.load(reply)['patient_id'], 'P001')
            self.assertEqual(mocked.call_args.args[0]['patient_id'], 'P001')

    def test_malformed_body(self):
        request = urllib.request.Request(self.base + '/api/generate', data=b'[]', headers={'Content-Type': 'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()


if __name__ == '__main__':
    unittest.main()
