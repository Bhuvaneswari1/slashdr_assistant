# SlashDr AI Assistant

## Render CSV hosting

See [RENDER_CSV_OPTIONS.md](RENDER_CSV_OPTIONS.md) for free hosting/storage alternatives and named, clinic-scoped cloud reviewer accounts. No production database has been deployed to Render.

## Full CSV data integration

All 28 relevant tables are imported locally (19,025,648 rows). See [CSV_INTEGRATION.md](CSV_INTEGRATION.md) for the Clinic ID input, local startup, patient search, data mappings and generation settings. The SQLite database stays in ignored `private_data/`; CSV mode never falls back to synthetic records; the existing Render deployment has not been switched to the local database.

## Deploy for client review

See [CLOUD_DEPLOYMENT.md](CLOUD_DEPLOYMENT.md) for the Render deployment steps. `render.yaml` declares the Python service, health check and environment values. Use the separate `slashdr-cloud-source.zip` for repository upload; it excludes `.env` and `.venv`. No cloud deployment has been completed just by preparing these files.

## Start the application with Swagger UI

The FastAPI entry point is now implemented in `api.py`. This resolves `Could not import module "api"` when running Uvicorn from this project folder. The original `app.py` remains available as a local-only legacy server.

First stop any old server or Uvicorn reloader with **Ctrl+C** in its terminal. Then run:

```bash
cd /Users/bhuvaneswarigokul/Documents/Codex/2026-10-31/wh/outputs/slashdr-assistant
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m uvicorn api:app --port 8000
```

If `.venv` does not exist yet, create it using `python3 -m venv .venv` before activating it. This command deliberately disables auto-reload, so changes inside `.venv` cannot trigger restart loops. Restart manually after changing Python files or `.env`. For development auto-reload, use `python3 -m uvicorn api:app --reload --reload-dir . --reload-exclude "$PWD/.venv" --port 8000`.

Open:

- Application: <http://127.0.0.1:8000/>
- Swagger UI: <http://127.0.0.1:8000/docs>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>
- Health check: <http://127.0.0.1:8000/health>

In Swagger, expand `POST /api/generate`, choose **Try it out**, and submit:

```json
{"patient_id": "P010", "question": "Summarise this patient before the next visit."}
```

The FastAPI routes reuse the existing LLM generation and citation-validation functions. UI responses retain the existing shape, including `error` on failures. Input validation failures use HTTP 422 and unknown patients use HTTP 404. Synthetic patient selection is not real clinical authorization.

To verify only the new routes and core logic without opening a network port:

```bash
PYTHONPATH=tests python3 -m unittest test_api test_app.CoreTests -v
```

For all tests, including the legacy localhost HTTP tests, run `python3 -m unittest discover -s tests -v` where local network access is allowed. New route tests call the ASGI app in memory and mock LLM generation; they do not spend API credits.

### Cloud review configuration

Deploy the FastAPI app as a Python web service. For Render:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn api:app --host 0.0.0.0 --port $PORT`
- Health-check path: `/health`
- Set `OPENAI_API_KEY`, `OPENAI_MODEL`, `REVIEW_USERNAME` and `REVIEW_PASSWORD` through the host's environment settings.
- Never use `--reload` in the cloud start command or upload `.env`/`.venv`.

`api.py` requires reviewer credentials when Render's `RENDER=true` environment flag is present. Outside Render, configure both reviewer variables explicitly to protect access. A partially configured username/password pair stops startup. With both set, HTTP Basic authentication protects the app, API, Swagger and OpenAPI JSON; the browser prompts for reviewer credentials. Only `/health` is public. Use HTTPS for remote review. This shared review login is for the synthetic-data demo, not per-doctor identity or patient authorization. No distributed rate limiter is implemented; limit the audience and configure API spend limits for the review.

The FastAPI entry point supports the deployed host rather than the legacy localhost-only Host restriction. It rejects browser requests with a different origin host; it does not enable cross-origin SwaggerHub calls. The local Swagger UI at `/docs` uses the same origin and needs no CORS configuration.

Deployment files are prepared locally; no cloud service has been created or deployed by adding `api.py`.

Step 1 is a local, read-only patient-record assistant with real LLM generation. A doctor selects a fictional patient, asks a question, reviews the generated answer, and opens the cited records. This package contains **100 synthetic patient histories**, not 100 separate datasets and not model training data.

## Use case and first application step

Before a consultation, a doctor needs to understand a patient's recorded history quickly. This app supports visit summaries, questions about recorded allergies and medications, blood pressure history, and comparisons between visits. Answers must stay within supplied records and preserve dates, units and uncertainty.

Example workflow:
1. Select `P001`.
2. Click **Last 3 BP readings**.
3. Click **Generate answer**.
4. Read the answer and click its source buttons to open original entries.
5. Verify the numbers and wording. Optionally download the draft for review.

The expected BP evidence for P001 is:

| Date | Recorded BP |
| --- | --- |
| 2026-10-20 | 125/76 mmHg |
| 2026-09-18 | 123/75 mmHg |
| 2026-08-15 | 121/74 mmHg |

The LLM generates the wording at runtime. There are no canned answers or fallback answers presented as AI generation.

## Requirements

- Python 3.10 or later, including its standard SSL support.
- A browser and internet access to OpenAI for generation.
- Your own OpenAI API key, API billing/quota and access to the configured model.
- The Swagger entry point requires the packages in `requirements.txt`. The legacy `app.py` uses only the Python standard library. No Node.js, database or vector service is required.

## Setup step by step

### 1. Extract and open the project

Extract `slashdr-assistant.zip`. Open a terminal inside the extracted `slashdr-assistant` folder. All commands below run from that folder.

Check Python:

```bash
python3 --version
```

On Windows, use `py` instead of `python3` for the commands below.

### 2. Configure the API key

A `.env` file is included. Hidden files may not appear in your file browser. Open it in a text editor and replace the placeholder:

```dotenv
OPENAI_API_KEY=your_actual_key_here
OPENAI_MODEL=gpt-4.1-mini
PORT=8000
```

Create/manage your key at [OpenAI API keys](https://platform.openai.com/api-keys). This package cannot include a real personal key. Do not paste the key in chat, JavaScript or the README. Keep `.env` private; `.gitignore` excludes it from Git. If missing, copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Windows PowerShell equivalent: `Copy-Item .env.example .env`.

The loader supports simple `KEY=value` lines and optional surrounding quotes. It does not execute shell expressions, expand variables or support inline comments. Existing process environment variables take precedence over `.env`. Restart the app after changing configuration. `OPENAI_MODEL` can be changed to another Responses API model supporting structured outputs that your account can access.

### 3. Start the application

```bash
python3 app.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Leave the terminal running. Stop with `Ctrl+C`. If port 8000 is occupied, change `PORT` to `8001`, restart, and use the printed URL.

The server binds only to `127.0.0.1`. It is a local development app, not a hosted clinical service.

### 4. Try the initial use cases

- `P001`: prepare a visit summary or show the last three HbA1c results.
- `P004`: ask for allergies; the record says allergy status is not documented.
- `P003`: compare the two written MRI reports; both contain the same documented findings.
- `P002`: ask about medication status; the entry is historical and current use is unverified.
- Any patient: ask for an absent result; the answer should acknowledge missing evidence.

A configured key is not necessarily a valid key. The app verifies credentials only when you generate an answer. Generation sends the question and selected patient's records to OpenAI and may incur API charges.

### 5. Run the offline checks

```bash
python3 -m unittest discover -s tests -v
```

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Tests use mocked API responses and require no API key or network. They cover patient isolation, dataset counts, missing-data fixtures, malformed/refused/incomplete responses, invalid citations, missing credentials and API request construction. They do not validate clinical quality or live model behavior.

### 6. Regenerate the sample dataset if needed

```bash
python3 generate_data.py
```

This overwrites `data/patients.json` with the same deterministic 100 fictional histories. Restart the app afterward; records are loaded at startup.

## Files and their purpose

```text
slashdr-assistant/
├── api.py                 FastAPI server, Swagger UI, review login and cloud entry point
├── app.py                 Legacy local HTTP server and API routes
├── core.py                Configuration, patient selection, prompt, OpenAI request, validation
├── generate_data.py       Reproducible synthetic data generator
├── data/
│   └── patients.json      Exactly 100 fictional patients, each with three visits
├── static/
│   ├── index.html         Patient selector, question form and source viewer
│   ├── style.css          Responsive interface styling
│   └── app.js             Browser interaction and server requests
├── tests/
│   ├── test_app.py        Core unit and legacy HTTP integration tests
│   └── test_api.py        FastAPI routes, Swagger and reviewer login tests
├── .env                   Local API key placeholder and model/port settings
├── .env.example           Shareable configuration template
├── .gitignore             Excludes keys and local Python artifacts
├── requirements.txt       FastAPI and Uvicorn dependencies
└── README.md              Use case, setup, architecture and next steps
```

## How LLM generation works

```text
Browser: select patient + ask question
    → Python resolves patient ID against the local dataset
    → Only that patient's records are placed in the request
    → OpenAI Responses API generates structured JSON
    → Python validates answer fields and source identifiers
    → Browser displays answer, gaps and links to source records
```

This first increment sends the selected patient's complete small history as context. It uses no embeddings, vector search, fine-tuning or training. The 100 histories are records to query. They do not teach the model medical knowledge. Large real histories will need bounded retrieval before generation.

The backend uses HTTPS POST to `https://api.openai.com/v1/responses`, a configurable model, `store: false`, a 60-second network timeout and a 1,600-output-token limit. `store: false` disables response storage for later retrieval; it is not a guarantee of zero provider retention. JSON-schema output contains `answer`, `source_ids`, and `missing_information`.

The server rejects unknown source IDs, citations from other patients and invalid JSON. It accepts grouped citations such as `[P010-V1, P010-V2]`, normalizes whitespace and separators, and builds the source buttons from validated inline citations. Valid extra or omitted IDs in the redundant source list no longer cause an otherwise valid answer to fail. Unknown IDs in either location are always rejected. If the answer has no inline citations, its validated source list is displayed as answer-level evidence; the app does not invent sentence-level citations. A valid source ID does **not** prove the answer is supported by that source. Clinical and semantic correctness require review. The prompt's restrictions are instructions to the model, not guaranteed protections against every malicious question.

## Dataset structure

Each patient has `patient_id`, `clinic_id`, fictional `name`, `synthetic: true`, and a `records` array. Each record has a unique `record_id`, `type` and clinical `date`. Visit-linked vitals and notes have `encounter_id`.

There are five repeating scenario templates: diabetes, hypertension, back pain, asthma and routine review. All patients have a profile and three encounters with vitals and notes. Scenario-dependent records add HbA1c results, medication entries or written MRI reports. Some allergies/results are deliberately missing. The scenarios are programmatically varied fixtures, not 100 clinically authored independent cases; they are unsuitable as a clinical benchmark.

No real names, phone numbers, addresses, uploaded documents, audio or raw scans are included. Synthetic medication entries demonstrate record handling and are not prescribing guidance. All fixtures are in one demo clinic. The app has no authenticated doctor identity or real clinic authorization system.

## Local API routes

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/status` | Configuration presence, model name and patient count; never the key |
| GET | `/api/patients` | Fictional patient names and IDs |
| GET | `/api/patient?id=P001` | Selected patient's complete synthetic records |
| POST | `/api/generate` | Generate from JSON with `patient_id` and `question` |

Only static files on an explicit allowlist are served. `.env`, source code and data files are not directly exposed as static downloads. The legacy app.py applies localhost Host and Origin checks; api.py supports a cloud host with same-origin browser checks and optional reviewer login. Model text is rendered using `textContent`, never executed as HTML. Switching patients clears the answer and discards responses belonging to an earlier selection. Generated answers are held in browser memory and are not written to patient records.

## Troubleshooting

| Problem | Action |
| --- | --- |
| Generate button disabled | Add a real key to `.env`, then restart and refresh |
| API key rejected | Check the key and whether a process environment variable overrides `.env` |
| Quota or rate limit | Check API billing/limits; retry later |
| Model access error | Configure a model you can access that supports the required API and schema |
| Network error | Check internet, proxy and Python SSL configuration |
| Source validation failed | Read the specific reason: unknown source or malformed brackets; the answer remains withheld |
| Incomplete generation | Ask a narrower question; no partial answer is shown |
| Address already in use | Change `PORT` and restart |
| Dataset file missing | Run `python3 generate_data.py`, then start the app |

## Scope and next development step

This deliverable implements the first **LLM generation pilot**. OCR, PDF upload, voice dictation, Tamil translation workflows, authenticated permissions, approved chart updates and clinical decision support are later increments. Do not put real patient data into this prototype. Before a real deployment, implement authenticated patient/clinic permissions, governed integrations, audit controls, appropriate provider data arrangements and clinician-reviewed evaluation. No automatic record writes or medical actions are implemented.

Next, create a clinician-reviewed evaluation set with expected answers and source records. Once the narrow tasks are validated, replace synthetic record loading with authorized SlashDr API access and add retrieval for larger histories.

## Official API references

- [Text generation and Responses API](https://developers.openai.com/api/docs/guides/text)
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [GPT-4.1 mini model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini)

Verification after the citation fix: all 26 offline and HTTP tests passed. A live OpenAI summary request for synthetic patient P010 also passed source validation with seven source records. This verifies that request, not overall clinical accuracy. The automated test suite uses mocks and makes no API calls.

## Citation fix and restarting an existing installation

The citation parser now accepts comma/semicolon/pipe/ampersand/and-separated IDs within brackets, optional backticks and whitespace. It normalizes them to individual references and removes duplicates. The request schema restricts `source_ids` to the selected patient’s actual record IDs. Source-list differences are reconciled only after all provided identifiers pass validation. When there are no inline citations, the validated source list is retained for the source buttons. This does not verify whether each claim is supported by its cited record.

If the application was already running, stop it with `Ctrl+C`, run `python3 app.py` from this folder again, and refresh the browser. Python does not reload source changes automatically. Your local `.env` is unchanged. The downloadable archive always contains the placeholder `.env.example` content as `.env`; preserve your own key when replacing an existing installation.

## Downloading answers

**Download answer for review** exports the selected patient ID, question, generated answer, source IDs and reported missing information as a text file. Developer evaluation metrics are not included in the application interface or download.

## Loading and layout improvements

Clinic status/count and the first patient-page request now load concurrently. Startup status and clinic options also load concurrently. Clinic counts are cached per configured store and clinic; restart the app after replacing the database. Visible loading messages distinguish record requests from disabled generation. A disabled Generate button is not a loading spinner: production generation remains off while `ALLOW_EXTERNAL_PATIENT_DATA=false`. No automatic generation retries were added.

Browser requests have bounded timeouts and clearer network/error messages. Render logs include `request_completed`, the method, route path, status and server elapsed milliseconds; they do not include patient IDs from query strings, questions, passwords or record contents. `Server-Timing` is available in the browser Network inspector. Compare that server timing with total browser request duration to investigate network vs server latency.

Spacing changes include a wider patient sidebar, shorter patient IDs in the CSV dropdown, separate clinic and pagination button spacing, a compact title area, aligned header/content widths, responsive question shortcuts and a generation-disabled explanation.


## Patient navigation and details (7 November 2026)

When a named account has only one authorized clinic, the application selects and loads that clinic automatically. The clinic field is disabled. Accounts with several authorized clinics retain clinic selection. Access restrictions are enforced by the server.

Previous patient / Next patient move one patient at a time, including across the 50-record page boundary. IDs sort numerically, rather than as text. Gaps are expected when intervening IDs belong to other clinics or do not exist. Exact-ID search remains available; clear the search to browse the clinic again.

**Patient details** opens a popup for the selected patient. It displays available personal fields and marks absent fields as unavailable. Changing patient clears and closes the popup. Original age/date values are shown without guessing their meaning.

Names and email come from a separate private UI profile index. They are not added to the LLM request. The main imported database does not need rebuilding or uploading again.

### Enable personal details on Render

1. Push the updated `api.py`, `csv_store.py`, and all three files in `static/` to GitHub, then deploy the latest commit on Render.
2. A private profile file has already been built locally at `private_data/patient_profiles.sqlite` (about 20 MB). To rebuild it from the original full export, run:

   ```bash
   python3 build_patient_profiles.py --source ../slashdr-table-csvs/people.csv
   ```

3. From your Mac Terminal, upload that file privately:

   ```bash
   scp -i ~/.ssh/render_slashdr_v2 private_data/patient_profiles.sqlite srv-dbkpen7b9u1s73839lu0@ssh.ohio.render.com:/var/data/patient_profiles.sqlite.uploading
   ```

4. In Render Shell, check the uploaded SQLite file and install it:

   ```bash
   python -c "import sqlite3; c=sqlite3.connect('file:/var/data/patient_profiles.sqlite.uploading?mode=ro', uri=True); print(c.execute('PRAGMA quick_check').fetchone()[0]); c.close()"
   ```

   After it prints `ok`, run:

   ```bash
   chmod 600 /var/data/patient_profiles.sqlite.uploading
   mv /var/data/patient_profiles.sqlite.uploading /var/data/patient_profiles.sqlite
   ```

5. The default profile location is alongside `CSV_DATABASE`. With `/var/data/slashdr.sqlite`, no additional environment variable is needed. Refresh the deployed page, then click **Patient details**. If the profile file is absent, the popup still shows available basic fields and explains that names/contact fields are unavailable.

Keep both databases and the original CSV exports out of GitHub. The source ZIP excludes them and `.env`.

Validation: `node tests/test_navigation.cjs` checks automatic clinic selection, sequential navigation, page boundaries, end-of-list behavior and popup clearing. Python tests check numeric ordering, clinic isolation, missing profile handling and exclusion of UI identity fields from clinical context.

Imported patient IDs display as `P` followed by the original numeric `people.id` (for example `P22791`). Exact search accepts either `P22791` or `22791`. The stored database ID remains unchanged; no reimport is needed.


## Active reviewer scope: Clinic 1 (9 November 2026)

The private `client-review` account configuration now authorizes only Clinic 1. Local `CSV_ALLOWED_CLINICS` is also set to `1`. The existing imported SQLite database already contains Clinic 1 (10,069 patients in the imported snapshot); no reimport or database upload is needed. Example patients are P1, P4, P11, P31 and P36. Existing patient profile lookup works with the same numeric source IDs.

To apply this to the hosted app, open Render → slashdr_assistant → Environment → Edit. In the existing `REVIEW_ACCOUNTS_JSON` value, change only the `client-review` account's `clinic_ids` from `["13"]` to `["1"]`. Preserve its existing password hash and any other named accounts. Save and deploy/restart. If `CSV_ALLOWED_CLINICS` is present on Render, set it to `1` as well; named-account clinic scopes control authenticated cloud access. Keep `DATA_MODE=csv` and the existing database path and external-generation setting.

Refresh the app after deployment. Clinic 1 will be selected automatically, and patient lists, record retrieval, personal details and generation requests will use that clinic. Do not commit the private account JSON or `.env` to GitHub. Clinic 1's name has not been verified; do not label it Saravanan's clinic based on the earlier Clinic 13 configuration.


## Patient trends & visit history (9 November 2026)

The former flat evidence list is replaced with latest dated measurement cards, a selectable BP/heart-rate/SpO₂/weight chart and a visit timeline. These are rendered directly from retrieved records without an additional LLM request. Chart dates retain the source date or the backend's stated appointment-date fallback; the source popup exposes the date basis.

A single recorded date shows points and a trend-unavailable explanation. Multiple readings on one date are retained, not averaged. Missing measurements at retrieved appointments break connecting lines. Nonnumeric values, unknown dates and unsupported units remain in the measurement table but are not plotted. Different measurements have separate charts and units. The overview is limited to the records retrieved by the existing API caps; it is not a complete lifetime chart.

The timeline groups linked entries by appointment ID, then by category. Separate appointments on the same day remain distinct. Unlinked records are explicitly labeled as date groups. Missing information is not treated as normal. Latest cards show all readings on the latest available date instead of choosing an arbitrary same-day reading.

Answer citations, measurement cards, chart points (mouse or Enter/Space), measurement-table source buttons and timeline sources open an original-record dialog. The bulk raw-record list is no longer shown on the main page. Patient changes clear the overview and close source dialogs.

Deploy the updated three files in `static/` to Render and refresh the browser. No database rebuild, extra dependency, environment change or patient-data upload is needed. Run `node tests/test_navigation.cjs` for chart and navigation regression checks, alongside the Python suite.


### Exact patient search and panel alignment

Patient search accepts an exact prefixed or numeric ID (for example P11, p11 or 11). Use Search or Enter; typing also searches after a short pause. Clear restores clinic browsing. No-match and invalid-ID messages appear beside the search field. In the imported Clinic 1 snapshot P12 is not available; P1, P4 and P11 are available. A numeric gap is not a search error, and search does not disclose another clinic's records. Editing the search immediately disables generation for the previous patient until a new match loads.

The patient and question panels now stretch to matching heights on desktop, with consistent control heights and spacing. Empty patient profiles no longer leave a divider or blank profile area. Mobile layouts retain stacked panels. Deploy the three updated static files; no database changes are required.

The patient search now uses a single input without helper text or Search/Clear buttons. Typing searches automatically; Enter searches immediately. Empty the input to restore clinic browsing.
