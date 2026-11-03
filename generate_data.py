"""Reproducible synthetic fixtures; no real patient information or clinical validation."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def generate():
    patients = []
    for i in range(1, 101):
        pid = f'P{i:03d}'
        condition = ['Type 2 diabetes', 'Hypertension', 'Back pain', 'Asthma', 'Routine review'][(i-1) % 5]
        records = [{
            'record_id': f'{pid}-PROFILE', 'type': 'profile', 'date': '2026-10-20',
            'age': 25 + i % 50, 'recorded_condition': condition,
            'allergy_status': 'Not documented' if i % 4 == 0 else 'Recorded allergy',
            'allergies': [] if i % 4 == 0 else [{'substance': 'Penicillin', 'reaction': 'Rash', 'verification': 'Patient reported'}],
        }]
        for visit, date in enumerate(['2026-08-15', '2026-09-18', '2026-10-20'], 1):
            records.extend([
                {'record_id': f'{pid}-V{visit}', 'type': 'vitals', 'date': date,
                 'encounter_id': f'{pid}-E{visit}', 'systolic': 118 + i % 25 + visit * 2,
                 'diastolic': 72 + i % 14 + visit, 'bp_unit': 'mmHg',
                 'weight': round(55 + i % 35 + visit * .2, 1), 'weight_unit': 'kg'},
                {'record_id': f'{pid}-N{visit}', 'type': 'consultation_note', 'date': date,
                 'encounter_id': f'{pid}-E{visit}', 'text': f'Review for {condition.lower()}. '
                 + ('Patient reports improvement since previous visit. ' if visit > 1 else 'Baseline history recorded. ')
                 + 'Examination findings not documented. Recorded plan: return for follow-up in four weeks.'}
            ])
            if condition == 'Type 2 diabetes' and not (i % 3 == 0 and visit == 2):
                records.append({'record_id': f'{pid}-L{visit}', 'type': 'lab_result', 'date': date,
                                'test': 'HbA1c', 'value': round(7 + i % 8 * .1 - visit * .1, 1), 'unit': '%', 'status': 'final'})
        if condition in ['Type 2 diabetes', 'Hypertension']:
            medicine = 'Metformin' if condition == 'Type 2 diabetes' else 'Amlodipine'
            records.append({'record_id': f'{pid}-M1', 'type': 'medication', 'date': '2026-08-15',
                            'drug': medicine, 'strength': '500 mg' if medicine == 'Metformin' else '5 mg',
                            'frequency': 'Once daily', 'status': 'historical; current use unverified'})
        if condition == 'Back pain':
            for n, date in enumerate(['2026-08-15', '2026-10-20'], 1):
                records.append({'record_id': f'{pid}-R{n}', 'type': 'radiology_report', 'date': date,
                                'modality': 'Lumbar MRI', 'page': 1,
                                'text': 'Mild disc bulge at L4-L5. No significant canal narrowing reported.'})
        patients.append({'patient_id': pid, 'clinic_id': 'DEMO-CLINIC', 'name': f'Synthetic Patient {i:03d}',
                         'synthetic': True, 'records': records})
    return patients

if __name__ == '__main__':
    path = ROOT / 'data' / 'patients.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(generate(), indent=2) + '\n', encoding='utf-8')
    print('Created exactly 100 synthetic patient histories.')
