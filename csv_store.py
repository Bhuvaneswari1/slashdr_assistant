"""Read-only, clinic-scoped access to the locally imported CSV database."""
import calendar
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parent
REQUEST_CLINICS = ContextVar('request_clinics', default=None)
VISIT_TABLES = ['person_states', 'person_summaries', 'vital_answers', 'history_answers',
                'symptoms_answers', 'diagnosis_answers', 'complaint_answers', 'prescriptions',
                'investigations', 'pdfs', 'pdf_patients', 'next_visit_instructions']
LOOKUPS = {'question_id': ('questions', ['name', 'unit', 'summary_name', 'question_type_id']),
           'complaint_id': ('complaints', ['name']),
           'category_id': ('categories', ['name']),
           'pharma_generic_id': ('pharma_generics', ['name', 'dosage', 'generic_id', 'unit_id']),
           'medicine_type_id': ('medicine_types', ['name']),
           'instruction_id': ('instructions', ['title', 'english', 'tamil', 'telugu', 'hindi', 'clinic_id'])}


class DataError(Exception):
    pass


def month_range(question):
    for month in range(1, 13):
        match = re.search(r'\b(?:' + calendar.month_name[month] + '|' + calendar.month_abbr[month] + r')\s+(20\d{2})\b', question, re.I)
        if match:
            year = int(match[1]); end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
            return f'{year:04d}-{month:02d}-01', f'{end_year:04d}-{end_month:02d}-01'
    match = re.search(r'\b(20\d{2})-(0[1-9]|1[0-2])\b', question)
    if match:
        year, month = map(int, match.groups()); ey, em = (year + 1, 1) if month == 12 else (year, month + 1)
        return f'{year:04d}-{month:02d}-01', f'{ey:04d}-{em:02d}-01'
    return None


@contextmanager
def profile_connection(path):
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


class CsvStore:
    def __init__(self, path, allowed_clinics):
        self.path = Path(path).resolve()
        self.allowed_clinics = set(allowed_clinics)
        if not self.path.is_file():
            raise DataError('CSV database missing. Run csv_import.py before enabling CSV mode.')
        if not self.allowed_clinics:
            raise DataError('Configure CSV_ALLOWED_CLINICS before opening production records.')
        with self.connection() as db:
            try:
                self.tables = {r['table_name'] for r in db.execute('SELECT table_name FROM import_metadata')}
            except sqlite3.Error:
                raise DataError('The configured file is not an imported SlashDr CSV database.') from None

    def clinic(self, clinic_id):
        if not clinic_id or not re.fullmatch(r'\d+', str(clinic_id)):
            raise DataError('Enter a numeric Clinic ID first.')
        if '*' not in self.allowed_clinics and str(clinic_id) not in self.allowed_clinics:
            raise DataError('This clinic is outside the configured access scope.')
        return str(clinic_id)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        try:
            yield db
        finally:
            db.close()

    def clinics(self):
        with self.connection() as db:
            rows = db.execute('SELECT DISTINCT clinic_id FROM clinic_patients ORDER BY clinic_id')
            return [{'clinic_id': r['clinic_id'], 'name': 'Clinic ' + r['clinic_id']} for r in rows
                    if '*' in self.allowed_clinics or r['clinic_id'] in self.allowed_clinics]

    @lru_cache(maxsize=256)
    def patient_count(self, clinic_id):
        clinic_id = self.clinic(clinic_id)
        with self.connection() as db:
            return db.execute('SELECT COUNT(*) FROM clinic_patients c JOIN people p ON p.id=c.person_id WHERE c.clinic_id=?', (clinic_id,)).fetchone()[0]

    def patients(self, clinic_id, search='', limit=50, offset=0):
        clinic_id = self.clinic(clinic_id)
        search = search.strip()
        if search.upper().startswith('P'):
            search = search[1:]
        if search and not search.isdigit():
            return []
        with self.connection() as db:
            sql = 'SELECT p.id FROM clinic_patients c JOIN people p ON p.id=c.person_id WHERE c.clinic_id=?'
            args = [clinic_id]
            if search:
                sql += ' AND p.id=?'; args.append(search)
            sql += ' ORDER BY CAST(p.id AS INTEGER), p.id LIMIT ? OFFSET ?'; args.extend([min(limit, 100), offset])
            return [{'patient_id': 'P' + r['id'], 'name': 'Patient ' + r['id']} for r in db.execute(sql, args)]

    def personal_info(self, patient_id, clinic_id):
        clinic_id = self.clinic(clinic_id)
        match = re.fullmatch(r'P(\d+)', patient_id or '')
        if not match:
            raise DataError('Select an imported patient ID.')
        person_id = match[1]
        with self.connection() as db:
            row = db.execute('SELECT p.* FROM people p JOIN clinic_patients c ON p.id=c.person_id WHERE p.id=? AND c.clinic_id=?', (person_id, clinic_id)).fetchone()
            if not row:
                raise DataError('Patient not found within the selected clinic.')
            profile = dict(row)
            last_visit = db.execute('SELECT MAX(date) FROM appointments WHERE person_id=? AND clinic_id=?', (person_id, clinic_id)).fetchone()[0]
            allergy = self.catalog(db, 'allergies', profile.get('allergy'))
            if allergy and allergy.get('clinic_id') in (None, '', '0', clinic_id):
                allergy_text = allergy.get('name')
            else:
                allergy_text = profile.get('allergy')
        ui_path = Path(os.environ.get('UI_PROFILE_DATABASE', str(self.path.with_name('patient_profiles.sqlite')))).resolve()
        ui_profile = {}
        if ui_path.is_file():
            if os.environ.get('RENDER') == 'true' and not ui_path.is_relative_to(Path(os.environ.get('CSV_STORAGE_DIR', '/var/data')).resolve()):
                raise DataError('UI_PROFILE_DATABASE must be inside CSV_STORAGE_DIR.')
            with profile_connection(ui_path) as ui_db:
                row = ui_db.execute('SELECT * FROM patient_profiles WHERE id=?', (person_id,)).fetchone()
                if row:
                    ui_profile = dict(row)
        display = ui_profile.get('display_name') or ' '.join(str(ui_profile[k]).strip() for k in ['salutation', 'initial', 'name', 'last_name'] if ui_profile.get(k))
        fields = {
            'Patient ID': patient_id, 'Clinic ID': clinic_id,
            'Name': display or None,
            'Sex (as recorded)': profile.get('sex'),
            'Recorded age or date value': profile.get('age'),
            'Age/date format code (uninterpreted)': profile.get('age_type'),
            'Email': ui_profile.get('email'),
            'Allergy entry (as recorded)': allergy_text,
            'Latest appointment in this clinic': last_visit,
        }
        return {'patient_id': patient_id, 'clinic_id': clinic_id, 'fields': fields,
                'profile_details_available': bool(ui_profile),
                'note': 'Personal information is displayed for the authorized reviewer only and is not added to the LLM context. '
                        + ('' if ui_profile else 'The optional patient profile file is not installed or has no matching patient. Names/contact fields are unavailable.')}

    def catalog(self, db, table, source_id):
        if table not in self.tables or source_id in (None, ''):
            return None
        row = db.execute(f'SELECT * FROM "{table}" WHERE id=?', (source_id,)).fetchone()
        return dict(row) if row else None

    def enrich(self, db, data, clinic_id):
        context = {}
        for field, (table, columns) in LOOKUPS.items():
            row = self.catalog(db, table, data.get(field))
            if row:
                # Instructions may be clinic-specific; don't borrow another clinic's text.
                if table == 'instructions' and row.get('clinic_id') not in (None, '', '0', clinic_id):
                    continue
                context[field] = {'source_table': table, 'source_id': row['id'],
                                  **{c: row.get(c) for c in columns}}
                if field == 'pharma_generic_id':
                    generic = self.catalog(db, 'generics', row.get('generic_id'))
                    if generic:
                        context[field]['generic_names'] = {k: v for k, v in generic.items() if k in ['name', 'name1', 'name2', 'name3', 'name4', 'name5']}
                    unit = self.catalog(db, 'units', row.get('unit_id'))
                    if unit:
                        context[field]['unit_label'] = unit.get('name')
        # Resolve numeric answer-option references only if the question association matches.
        question_id = data.get('question_id')
        raw = data.get('answer') or ''
        if question_id and re.fullmatch(r'\d+(?:\s*,\s*\d+)*', raw):
            options = []
            for option_id in raw.split(',')[:30]:
                option = self.catalog(db, 'possible_answers', option_id.strip())
                if option and option.get('question_id') == question_id:
                    options.append({'id': option['id'], 'name': option.get('name'), 'summary': option.get('summary')})
            if options:
                context['possible_answers'] = options
        if context:
            data['lookup_context'] = context
        return data

    def patient(self, patient_id, clinic_id, question=''):
        clinic_id = self.clinic(clinic_id)
        match = re.fullmatch(r'P(\d+)', patient_id or '')
        if not match:
            raise DataError('Select an imported patient ID, such as P123.')
        person_id = match[1]
        with self.connection() as db:
            profile = db.execute('SELECT p.* FROM people p JOIN clinic_patients c ON p.id=c.person_id WHERE p.id=? AND c.clinic_id=?', (person_id, clinic_id)).fetchone()
            if not profile:
                raise DataError('Patient not found within the selected clinic.')
            profile = dict(profile)
            interval = month_range(question)
            clauses = 'person_id=? AND clinic_id=?'; params = [person_id, clinic_id]
            if interval:
                clauses += ' AND date>=? AND date<?'; params.extend(interval)
            visit_count = db.execute('SELECT COUNT(*) FROM appointments WHERE ' + clauses, params).fetchone()[0]
            visits = [dict(r) for r in db.execute('SELECT * FROM appointments WHERE ' + clauses + ' ORDER BY date DESC, id DESC LIMIT 100', params)]
            notes = [
                'Records are limited to the selected clinic; identifiers are source IDs, not verified clinical facts.',
                'Medication is_active flags do not establish current medication use.',
                'PDF rows are metadata only; document contents have not been extracted.',
                'Raw allergy values are not interpreted as confirmed absence of allergies.',
            ]
            if interval:
                notes.append(f'Visit-date filter: {interval[0]} inclusive to {interval[1]} exclusive. This is based on appointment dates, not independently verified observation collection dates.')
            if visit_count > len(visits):
                notes.append(f'Only the most recent {len(visits)} of {visit_count} matching visits were searched. Older visits were omitted.')
            p_fields = ['age', 'age_type', 'sex', 'allergy', 'is_active']
            first = {'record_id': f'{patient_id}-people-{person_id}', 'type': 'profile',
                     'date': 'Not recorded', 'age': profile.get('age'),
                     'recorded_condition': 'See recorded diagnoses',
                     'source_table': 'people', 'source_id': person_id,
                     'data': {k: profile.get(k) for k in p_fields}}
            allergy = self.catalog(db, 'allergies', profile.get('allergy'))
            if allergy and allergy.get('clinic_id') in (None, '', '0', clinic_id):
                first['data']['allergy_catalog_match'] = {'id': allergy['id'], 'name': allergy.get('name')}
            candidates = []
            visit_ids = [v['id'] for v in visits]
            dates = {v['id']: v.get('date') or 'Not recorded' for v in visits}
            def add(table, row, date):
                source_date = row.get('date') or row.get('start_date')
                if not source_date or not re.match(r'^\d{4}-(?:0[1-9]|1[0-2])-', source_date):
                    source_date = None
                if interval and source_date and not interval[0] <= source_date[:10] < interval[1]:
                    return
                candidates.append({'record_id': f'{patient_id}-{table}-{row["id"]}',
                    'type': table, 'date': source_date or date,
                    'date_basis': 'source date' if source_date else 'appointment date or unavailable; observation collection date not verified',
                    'source_table': table, 'source_id': row['id'],
                    'data': self.enrich(db, row, clinic_id)})
            for visit in visits:
                data = {k: v for k, v in visit.items() if k not in ['token']}
                doctor = self.catalog(db, 'doctors', visit.get('doctor_id'))
                clinic = self.catalog(db, 'clinics', clinic_id)
                if doctor:
                    data['doctor'] = {'id': doctor['id'], 'name': doctor.get('name'), 'specialist': doctor.get('specialist')}
                if clinic:
                    data['clinic'] = {'id': clinic['id'], 'name': clinic.get('name')}
                add('appointments', data, dates[visit['id']])
            if visit_ids:
                placeholders = ','.join('?' for _ in visit_ids)
                for table in VISIT_TABLES:
                    for row in db.execute(f'SELECT r.* FROM "{table}" r JOIN appointments a ON a.id=r.appointment_id WHERE r.appointment_id IN ({placeholders}) ORDER BY a.date DESC, r.created_at DESC, r.id DESC LIMIT 501', visit_ids):
                        row = dict(row)
                        # An investigations row with a conflicting person_id is not trusted.
                        if table == 'investigations' and row.get('person_id') not in (None, '', person_id):
                            continue
                        add(table, row, dates[row['appointment_id']])
                    if sum(c['source_table'] == table for c in candidates) >= 501:
                        notes.append(f'{table} retrieval was capped; some matching records may be omitted.')
            # These tables have no clinic ownership column; use them only when ownership is unambiguous.
            clinic_count = db.execute('SELECT COUNT(*) FROM clinic_patients WHERE person_id=?', (person_id,)).fetchone()[0]
            if clinic_count == 1:
                for table in ['standing_diagnoses', 'past_visits']:
                    sql = f'SELECT * FROM "{table}" WHERE person_id=?'
                    args = [person_id]
                    field = 'start_date' if table == 'standing_diagnoses' else 'date'
                    if interval:
                        sql += f' AND "{field}">=? AND "{field}"<?'; args.extend(interval)
                    for row in db.execute(sql + f' ORDER BY "{field}" DESC LIMIT 101', args):
                        row = dict(row); add(table, row, row.get(field) or 'Not recorded')
            else:
                notes.append('Person-level standing diagnoses and outside-visit notes were excluded because their clinic ownership is ambiguous.')
            # Select relevant records within the authorized set, never using LLM-written SQL.
            words = set(re.findall(r'[a-z]{3,}', question.lower())) - {'the', 'this', 'patient', 'show', 'with', 'and', 'for', 'recorded', 'what', 'only'}
            preferred = set()
            for terms, tables in [(['blood pressure', 'bp', 'weight', 'vital'], ['vital_answers', 'appointments']),
                                 (['medication', 'prescri', 'medicine'], ['prescriptions']),
                                 (['history', 'timeline'], ['history_answers', 'past_visits']),
                                 (['diagnos'], ['diagnosis_answers', 'standing_diagnoses']),
                                 (['investigation', 'report', 'lab', 'hba1c'], ['investigations', 'vital_answers', 'pdfs', 'pdf_patients'])]:
                if any(term in question.lower() for term in terms):
                    preferred.update(tables)
            def score(record):
                text = json.dumps(record['data'], ensure_ascii=False).lower()
                return ((5 if record['source_table'] in preferred else 0) + sum(w in text for w in words), record['date'], record['record_id'])
            candidates.sort(key=score, reverse=True)
            records = [first]; size = len(json.dumps(first, ensure_ascii=False)); omitted = 0
            for record in candidates:
                length = len(json.dumps(record, ensure_ascii=False))
                if len(records) >= 120 or size + length > 60000:
                    omitted += 1; continue
                records.append(record); size += length
            if omitted:
                notes.append(f'{omitted} retrieved records were omitted from the answer context to respect size limits. Narrow the question or specify a month.')
            return {'patient_id': patient_id, 'clinic_id': clinic_id, 'name': 'Patient ' + person_id,
                    'synthetic': False, 'records': records,
                    'context_scope': {'matching_visits': visit_count, 'searched_visits': len(visits),
                                      'included_records': len(records), 'notes': notes}}


@lru_cache(maxsize=4)
def _cached_store(path, clinics):
    return CsvStore(path, clinics)


def get_store():
    mode = os.environ.get('DATA_MODE', 'csv')
    if mode == 'synthetic':
        return None
    if mode != 'csv':
        raise DataError('DATA_MODE must be synthetic or csv.')
    cloud = os.environ.get('RENDER') == 'true'
    if cloud and os.environ.get('CLOUD_CSV_ENABLED') != 'true':
        raise DataError('Cloud CSV access is not configured. Set CLOUD_CSV_ENABLED=true after configuring the persistent disk and named reviewer accounts.')
    scoped = REQUEST_CLINICS.get()
    clinics = scoped if scoped is not None else tuple(c.strip() for c in os.environ.get('CSV_ALLOWED_CLINICS', '').split(',') if c.strip())
    path = os.environ.get('CSV_DATABASE', str(ROOT / 'private_data' / 'slashdr.sqlite'))
    if cloud:
        if scoped is None or not clinics or '*' in clinics:
            raise DataError('Cloud CSV access requires an authenticated named account with explicit clinic permissions.')
        storage = Path(os.environ.get('CSV_STORAGE_DIR', '/var/data')).resolve()
        if not Path(path).resolve().is_relative_to(storage):
            raise DataError('CSV_DATABASE must be inside the configured persistent CSV_STORAGE_DIR.')
    return _cached_store(path, clinics)
