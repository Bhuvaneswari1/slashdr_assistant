"""Create a small UI-only patient-name/contact index; never send it to the LLM."""
import argparse
import csv
import os
from pathlib import Path
import sqlite3
import sys

FIELDS = ['id', 'salutation', 'initial', 'name', 'last_name', 'display_name', 'email']


def build_profiles(source, output):
    source, output = Path(source), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + '.building')
    if temporary.exists():
        raise ValueError('A partial profile build exists. Check that no build is running first.')
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    db = sqlite3.connect(temporary)
    try:
        db.execute('CREATE TABLE patient_profiles (id TEXT PRIMARY KEY, salutation TEXT, initial TEXT, name TEXT, last_name TEXT, display_name TEXT, email TEXT)')
        csv.field_size_limit(sys.maxsize)
        count = 0
        with source.open(encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            if not set(FIELDS).issubset(reader.fieldnames or []):
                raise ValueError('Use the original full people.csv export, which includes patient names.')
            batch = []
            for row in reader:
                batch.append([None if row[k] == '\\N' else row[k] for k in FIELDS]); count += 1
                if len(batch) >= 5000:
                    db.executemany('INSERT INTO patient_profiles VALUES (?,?,?,?,?,?,?)', batch); batch.clear()
            if batch:
                db.executemany('INSERT INTO patient_profiles VALUES (?,?,?,?,?,?,?)', batch)
        db.commit()
        assert db.execute('SELECT COUNT(*) FROM patient_profiles').fetchone()[0] == count
        assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        db.close(); os.replace(temporary, output); output.chmod(0o600)
        print(f'Created UI-only profile index: {count:,} patients; {output.stat().st_size:,} bytes. No LLM calls made.')
        return count
    except BaseException:
        db.close(); temporary.unlink(missing_ok=True); raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'private_data/patient_profiles.sqlite')
    args = parser.parse_args()
    build_profiles(args.source, args.output)
