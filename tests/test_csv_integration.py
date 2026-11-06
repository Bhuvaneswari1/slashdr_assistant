import contextlib
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api
import core
from csv_import import import_directory, TABLES
from csv_store import CsvStore, DataError, month_range
from test_api import asgi_request
import asyncio

ROOT = Path(__file__).resolve().parents[1]


class CsvIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.source = cls.base / 'csv'; cls.source.mkdir()
        # Use the actual exported headers without loading production rows into test fixtures.
        header_map = json.loads((ROOT / 'tests' / 'fixtures' / 'csv_headers.json').read_text())
        data = {
            'people': [{'id':'1','age':'33','allergy':'1'}, {'id':'2','age':'44'}],
            'appointments': [
                {'id':'101','person_id':'1','clinic_id':'10','doctor_id':'1','date':'2026-09-18'},
                {'id':'102','person_id':'1','clinic_id':'20','date':'2026-10-20'},
                {'id':'201','person_id':'2','clinic_id':'20','date':'2026-09-18'}],
            'vital_answers': [
                {'id':'501','appointment_id':'101','question_id':'1','value':'120','date':'2026-09-18'},
                {'id':'502','appointment_id':'102','question_id':'1','value':'OTHER_CLINIC_SECRET'},
                {'id':'503','appointment_id':'201','question_id':'1','value':'OTHER_PATIENT_SECRET'},
                {'id':'504','appointment_id':'999','value':'ORPHAN_SECRET'}],
            'questions':[{'id':'1','name':'Systolic blood pressure','unit':'mmHg'}],
            'standing_diagnoses':[{'id':'1','person_id':'1','name':'AMBIGUOUS_CLINIC_SECRET'}],
            'clinics':[{'id':'10','name':'Clinic Ten'}, {'id':'20','name':'Clinic Twenty'}],
            'doctors':[{'id':'1','name':'Test doctor'}],
            'allergies':[{'id':'1','name':'Recorded test allergy','clinic_id':'10'}],
        }
        manifest=[]
        for name,headers in header_map.items():
            rows=data.get(name,[])
            with (cls.source/(name+'.csv')).open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=headers);writer.writeheader()
                for row in rows:
                    writer.writerow({key:row.get(key,'\\N') for key in headers})
            manifest.append({'table':name,'file':name+'.csv','row_count':len(rows)})
        with (cls.source/'manifest.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['table','file','row_count']);writer.writeheader();writer.writerows(manifest)
        cls.database=cls.base/'private'/'records.sqlite'
        with contextlib.redirect_stdout(io.StringIO()):
            cls.imported=import_directory(cls.source,cls.database)
        cls.store=CsvStore(cls.database,['10'])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_tables_and_row_counts_imported(self):
        with contextlib.closing(sqlite3.connect(self.database)) as db:
            rows=db.execute('SELECT table_name, row_count FROM import_metadata').fetchall()
        self.assertEqual({r[0] for r in rows}, TABLES)
        self.assertEqual(sum(r[1] for r in rows),self.imported)

    def test_clinic_search_and_unknown_patient(self):
        self.assertEqual(self.store.patients('10'),[{'patient_id':'DB-1','name':'Patient 1'}])
        self.assertEqual(self.store.patients('10','DB-2'),[])
        self.assertEqual(self.store.patient_count('10'),1)
        with self.assertRaises(DataError):self.store.patient('DB-2','10')
        with self.assertRaises(DataError):self.store.patient('DB-1','20')
        with self.assertRaises(DataError):self.store.patients('10 OR 1=1')
        with self.assertRaises(DataError):self.store.patients('')

    def test_patient_appointment_and_clinic_isolation(self):
        patient=self.store.patient('DB-1','10')
        content=json.dumps(patient)
        for secret in ['OTHER_CLINIC_SECRET','OTHER_PATIENT_SECRET','ORPHAN_SECRET','AMBIGUOUS_CLINIC_SECRET']:
            self.assertNotIn(secret,content)
        vital=next(r for r in patient['records'] if r['source_table']=='vital_answers')
        self.assertEqual(vital['data']['value'],'120')
        self.assertEqual(vital['data']['lookup_context']['question_id']['unit'],'mmHg')
        self.assertTrue(all(r['record_id'].startswith('DB-1-') for r in patient['records']))

    def test_date_filter_and_no_evidence(self):
        september=self.store.patient('DB-1','10','Show September 2026 observations')
        self.assertEqual(september['context_scope']['matching_visits'],1)
        october=self.store.patient('DB-1','10','Show October 2026 observations')
        self.assertEqual(october['context_scope']['matching_visits'],0)
        self.assertEqual(len(october['records']),1)
        self.assertEqual(month_range('December 2026'),('2026-12-01','2027-01-01'))

    def test_real_data_transmission_disabled_before_network(self):
        with patch.dict(os.environ,{'ALLOW_EXTERNAL_PATIENT_DATA':'false'}):
            with self.assertRaisesRegex(core.AppError,'External generation'):
                core.generate_answer(self.store.patient('DB-1','10'),'Summary',opener=lambda *a,**k:self.fail('Network must not be called'))

    def test_csv_routes_require_clinic_and_keep_source_records(self):
        result={'patient_id':'DB-1','answer':'BP recorded [DB-1-vital_answers-501].',
                'source_ids':['DB-1-vital_answers-501'],'missing_information':[]}
        with patch.dict(os.environ,{'DATA_MODE':'synthetic'}), patch('api.get_store',return_value=self.store), patch.multiple(api,REVIEW_USERNAME='',REVIEW_PASSWORD=''):
            status,body,_=asyncio.run(asgi_request('/api/patients?clinic_id=10'))
            self.assertEqual(status,200);self.assertEqual(len(json.loads(body)),1)
            self.assertEqual(asyncio.run(asgi_request('/api/patients'))[0],400)
            with patch('api.generate_answer',return_value=result):
                status,body,_=asyncio.run(asgi_request('/api/generate','POST',{'patient_id':'DB-1','clinic_id':'10','question':'BP'}))
                output=json.loads(body)
                self.assertEqual(status,200)
                self.assertEqual(output['source_records'][0]['source_id'],'501')
                self.assertIn('context_scope',output)

    def test_csv_mode_cannot_expose_data_without_auth_or_on_render(self):
        with patch.dict(os.environ,{'DATA_MODE':'csv'}),patch.multiple(api,REVIEW_USERNAME='',REVIEW_PASSWORD=''):
            self.assertEqual(asyncio.run(asgi_request('/api/patients?clinic_id=10'))[0],503)
        from csv_store import get_store
        with patch.dict(os.environ,{'DATA_MODE':'csv','RENDER':'true'}):
            with self.assertRaisesRegex(DataError,'local-only'):get_store()

    def test_read_only_database_and_no_overwrite(self):
        with self.store.connection() as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM people')
        with self.assertRaisesRegex(ValueError,'already exists'):
            import_directory(self.source,self.database)


if __name__=='__main__':unittest.main()
