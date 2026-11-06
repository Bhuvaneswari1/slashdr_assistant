"""Import the 28 local CSVs into an indexed SQLite database; never uploads data."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

TABLES = {
    'people', 'appointments', 'person_states', 'person_summaries', 'vital_answers',
    'history_answers', 'symptoms_answers', 'diagnosis_answers', 'complaint_answers',
    'standing_diagnoses', 'prescriptions', 'investigations', 'questions', 'possible_answers',
    'complaints', 'categories', 'allergies', 'pharma_generics', 'generics', 'medicine_types',
    'units', 'clinics', 'doctors', 'pdfs', 'pdf_patients', 'past_visits',
    'next_visit_instructions', 'instructions',
}


def ident(value):
    if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', value):
        raise ValueError('Invalid SQL identifier')
    return '"' + value + '"'


def import_directory(source, target, replace=False):
    source, target = Path(source).resolve(), Path(target).resolve()
    if target.exists() and not replace:
        raise ValueError('Database already exists. Use --replace to rebuild it.')
    with (source / 'manifest.csv').open(encoding='utf-8', newline='') as f:
        manifest = list(csv.DictReader(f))
    if {r['table'] for r in manifest} != TABLES or len(manifest) != len(TABLES):
        raise ValueError('Expected exactly the 28 assistant CSV tables in manifest.csv.')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    building = target.with_name(target.name + '.building')
    if building.exists():
        raise ValueError('An unfinished .building file exists. Check that no import is running before removing it.')
    csv.field_size_limit(sys.maxsize)
    fd = os.open(building, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(fd)
    connection = sqlite3.connect(building)
    try:
        connection.execute('PRAGMA journal_mode=OFF')
        connection.execute('PRAGMA synchronous=OFF')
        connection.execute('PRAGMA cache_size=-32768')
        connection.execute('CREATE TABLE import_metadata (table_name TEXT PRIMARY KEY, row_count INTEGER NOT NULL, columns_json TEXT NOT NULL)')
        total = 0
        for spec in manifest:
            table = spec['table']; path = (source / spec['file']).resolve()
            if not path.is_relative_to(source) or not path.is_file():
                raise ValueError('CSV path is outside the source directory or missing.')
            count = 0
            with path.open(encoding='utf-8', newline='') as f:
                reader = csv.reader(f); columns = next(reader)
                if len(columns) != len(set(columns)) or 'id' not in columns:
                    raise ValueError(f'Invalid columns in {table}')
                declaration = ', '.join(ident(c) + (' TEXT PRIMARY KEY' if c == 'id' else ' TEXT') for c in columns)
                connection.execute(f'CREATE TABLE {ident(table)} ({declaration})')
                sql = f'INSERT INTO {ident(table)} VALUES ({",".join("?" for _ in columns)})'
                batch = []
                for row in reader:
                    if len(row) != len(columns):
                        raise ValueError(f'CSV width mismatch in {table}')
                    batch.append([None if v == '\\N' else v for v in row]); count += 1
                    if len(batch) >= 5000:
                        connection.executemany(sql, batch); batch.clear()
                if batch:
                    connection.executemany(sql, batch)
            if count != int(spec['row_count']):
                raise ValueError(f'CSV row count differs from manifest for {table}')
            for key in ['appointment_id', 'person_id', 'question_id', 'clinic_id']:
                if key in columns:
                    connection.execute(f'CREATE INDEX {ident("idx_" + table + "_" + key)} ON {ident(table)} ({ident(key)})')
            if table == 'appointments':
                connection.execute('CREATE INDEX idx_appointments_scope ON appointments(clinic_id, person_id, date DESC, id DESC)')
                connection.execute('CREATE INDEX idx_appointments_person_clinic ON appointments(person_id, clinic_id)')
            connection.execute('INSERT INTO import_metadata VALUES (?, ?, ?)', (table, count, json.dumps(columns)))
            connection.commit(); total += count
            print(f'Imported {table}: {count:,} rows', flush=True)
        # Store one scoped patient index rather than scanning a million appointments per search.
        connection.execute('CREATE TABLE clinic_patients AS SELECT DISTINCT clinic_id, person_id FROM appointments WHERE person_id IS NOT NULL AND clinic_id IS NOT NULL')
        connection.execute('CREATE UNIQUE INDEX idx_clinic_patients_scope ON clinic_patients(clinic_id, person_id)')
        connection.execute('CREATE INDEX idx_clinic_patients_person ON clinic_patients(person_id, clinic_id)')
        connection.commit()
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed')
        connection.close()
        os.replace(building, target)
        print(f'Import complete: {len(manifest)} tables, {total:,} rows. Database: {target}', flush=True)
        return total
    except BaseException:
        connection.close()
        building.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=Path(__file__).resolve().parent / 'private_data' / 'slashdr.sqlite')
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args()
    import_directory(args.source, args.database, args.replace)
