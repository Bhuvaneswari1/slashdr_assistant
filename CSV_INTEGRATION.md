# Full CSV integration

The project can now read all 28 assistant-related CSV tables through a locally imported SQLite database. The current import contains **19,025,648 source rows**. This is data retrieval, not model training. Clinical answers remain drafts requiring verification.

## Run the integrated local application

The local `.env` is configured for CSV mode, local clinic selection, and external generation disabled. Reviewer credentials and the existing API key are preserved. Stop the previous server, then run:

```bash
cd /Users/bhuvaneswarigokul/Documents/Codex/2026-10-31/wh/outputs/slashdr-assistant
source .venv/bin/activate
python3 -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>, sign in, enter a Clinic ID using the available suggestions, and click **Load clinic patients**. Patient labels use `DB-<original person ID>` because the exported input intentionally omitted names. Browse 50 patients per page or search an exact original ID or `DB-` ID. No synthetic patient is mixed with imported records.

Use the FastAPI `api.py` entry point for CSV mode. The legacy `python3 app.py` serves the synthetic demo only.

## Local configuration

```dotenv
DATA_MODE=csv
CSV_ALLOWED_CLINICS=*
ALLOW_EXTERNAL_PATIENT_DATA=false
```

`*` allows the trusted local reviewer to select any imported clinic. Narrow it to a comma-separated allowlist, such as `CSV_ALLOWED_CLINICS=10,20`, to reject other clinic IDs. The backend rechecks this scope on patient lists, record access and generation. Clinic input is not a replacement for real per-user clinic authorization. CSV mode requires reviewer credentials and is blocked for non-loopback clients and on Render.

By default the database is `private_data/slashdr.sqlite`; set `CSV_DATABASE` to an absolute path to use a different location. All production data and database files are ignored by Git and excluded from deployment archives. `.env.example` now defaults to CSV mode; an isolated synthetic demonstration requires setting `DATA_MODE=synthetic` explicitly.

## LLM generation with production records

Production data has not been sent to OpenAI during this integration. You can inspect records locally with external generation disabled. `ALLOW_EXTERNAL_PATIENT_DATA=true` explicitly enables sending the selected clinic/patient's bounded record context and question to OpenAI using the configured API key. Only set it after approving that transmission and the provider/deployment arrangements for the actual patient data. Restart after changing it. The data may contain identifying free text; the database is not de-identified.

## Import or rebuild

The complete import has already been performed on this computer. To recreate it from the all-records CSV folder:

```bash
python3 csv_import.py --source ../slashdr-ai-csv-all-records
```

If a database already exists, the command stops rather than overwriting it. For an intentional rebuild, stop the app and add `--replace`. The importer builds a private temporary database, checks every CSV row count against the manifest, creates indexes, runs SQLite integrity checks, and atomically replaces the target only on success. It does not execute SQL from the supplied dump or upload any data. A crash may leave a `.building` file; confirm no import is running before removing that partial file.

## Mapping and retrieval

- `people.id` joins `appointments.person_id`. `appointments.clinic_id` establishes the visit scope. Patients without a linked appointment in that clinic are not listed.
- Answer, summary, prescription, investigation and document metadata rows join through `appointment_id`. Orphan rows are imported but not attributed to an arbitrary patient. An investigation row with a conflicting person ID is excluded.
- Question, category, complaint, medicine, generic, unit and instruction catalogs enrich linked evidence. Numeric answer-option references are resolved only when their `question_id` matches. Raw values are preserved.
- `allergies` is a catalog, not a direct patient-allergy association. Only exact source-ID matches in `people.allergy` are shown as catalog matches, without inferring “no allergies”.
- `standing_diagnoses` and `past_visits` lack clinic ownership. They are only included when the patient has visits in one clinic; otherwise they are excluded with an explicit scope note. Shared global person notes were not placed in the model context.
- `pdfs` and `pdf_patients` provide metadata only. No PDF or image contents were fetched or interpreted.
- Database status flags do not establish clinically verified current medication use or normal findings.

Each request searches up to 100 recent matching clinic visits and up to 501 rows per visit-related table. A maximum of 120 records and approximately 60,000 record characters enter the answer context. Relevant table types and matching text rank the candidate records. This is bounded, deterministic retrieval, not vector RAG. The UI and model receive explicit omission notes. Questions requiring complete all-time counts may exceed these limits; do not interpret omitted evidence as absence.

Month expressions such as `September 2026` or `2026-09` filter appointment dates. A record with an explicit source date outside that month is excluded. Missing observation dates are not independently reconstructed; the date basis is shown. Records in other-month appointments with a different observation date may require a different query. Source IDs point to actual imported rows. Answers returned with older cited rows include those source rows so the UI can open them even if the initial preview did not contain them.

## Verification

```bash
PYTHONPATH=tests python3 -m unittest test_csv_integration test_api test_app.CoreTests -v
```

Tests use fictional fixtures and verify complete table import, headers/counts, clinic and patient isolation, orphan handling, lookup enrichment, month filtering, external-data transmission gating, read-only access, API responses and synthetic-mode compatibility. No production LLM call is part of the tests. The real database was also opened read-only and a patient/clinic linkage sample was checked without printing clinical content.

## Files

- `csv_import.py`: streaming CSV importer and indexed database builder.
- `csv_store.py`: read-only clinic/patient lookup, joins and bounded context selection.
- `private_data/slashdr.sqlite`: local production index, excluded from Git and archives.
- `private_data/import_summary.json`: local row-count and sample-verification report.
- `api.py`: clinic input API and synthetic/CSV routing.
- `static/index.html` and `static/app.js`: Clinic ID input, patient pagination/search and scope display.

Keep the Render demo in synthetic mode. Moving real records to cloud requires a separate deployment design with per-user authorization, audited access, private persistent storage and governed external model usage; this local integration does not implement those production controls.

## CSV is the default source

The FastAPI application no longer opens `synthetic.json` at startup. The default is `DATA_MODE=csv`. It reads the indexed import of the original CSV files from `CSV_DATABASE`, never a synthetic fallback. Missing or restricted CSV configuration raises a setup error. Synthetic JSON is only opened if `DATA_MODE=synthetic` is deliberately selected.

This change does not copy the database to Render or remove the existing local-only restriction. A Render service explicitly set to synthetic mode still uses synthetic data until its environment is changed. Production CSV hosting remains a separate deployment task; do not change that service to CSV mode expecting data to appear without private storage and authorization being configured.

## Updated Render access

Cloud CSV mode can now use named reviewer accounts with per-user clinic scopes instead of the old blanket local-only restriction. Storage still must be provisioned separately; nothing has been uploaded or deployed automatically. See [RENDER_CSV_OPTIONS.md](RENDER_CSV_OPTIONS.md) for free-hosting alternatives and account configuration. Earlier local-only statements in this document describe the initial integration and are superseded by this section.
