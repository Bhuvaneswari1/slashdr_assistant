"""FastAPI entry point: python3 -m uvicorn api:app --port 8000."""
import base64
import binascii
import os
import secrets
import time
import logging
from functools import lru_cache
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from core import ROOT, AppError, generate_answer, load_env, load_patients, select_patient
from csv_store import DataError, REQUEST_CLINICS, get_store
from review_auth import AuthConfigError, authenticate_account, parse_accounts
from starlette.concurrency import run_in_threadpool

load_env()


@lru_cache(maxsize=1)
def synthetic_patients():
    # Explicit demonstration mode only. CSV startup never opens a JSON dataset.
    if os.environ.get('DATA_MODE', 'csv') != 'synthetic':
        raise DataError('Synthetic records are disabled in CSV mode.')
    return load_patients()
REVIEW_USERNAME = os.environ.get('REVIEW_USERNAME', '')
REVIEW_PASSWORD = os.environ.get('REVIEW_PASSWORD', '')
if bool(REVIEW_USERNAME) != bool(REVIEW_PASSWORD):
    raise RuntimeError('Set both REVIEW_USERNAME and REVIEW_PASSWORD, or leave both unset for local development.')
if os.environ.get('RENDER') == 'true' and not REVIEW_PASSWORD and not os.environ.get('REVIEW_ACCOUNTS_JSON'):
    raise RuntimeError('Configure REVIEW_ACCOUNTS_JSON (or legacy demo credentials) before starting the Render service.')

app = FastAPI(
    title='SlashDr Patient Records API', version='1.1.0',
    description='Read-only patient record assistant. Answers require clinician verification. '
                'The OpenAI key stays on the server. Reviewer credentials, if configured, use HTTP Basic authentication.',
)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    patient_id: str = Field(pattern=r'^(?:P\d{3}|DB-\d+)$', examples=['P010', 'DB-123'])
    clinic_id: str | None = Field(default=None, pattern=r'^\d+$')
    question: str = Field(min_length=1, max_length=2000,
                          examples=['Summarise this patient before the next visit.'])


class GenerateResponse(BaseModel):
    patient_id: str
    answer: str
    source_ids: list[str]
    missing_information: list[str]
    source_records: list[dict] = Field(default_factory=list)
    context_scope: dict | None = None


class PatientSummary(BaseModel):
    patient_id: str
    name: str


@app.middleware('http')
async def review_controls(request: Request, call_next):
    started = time.perf_counter()
    scoped_clinics = None
    protected = request.url.path != '/health'
    csv_mode = os.environ.get('DATA_MODE', 'csv') == 'csv'
    cloud = os.environ.get('RENDER') == 'true'
    account_json = os.environ.get('REVIEW_ACCOUNTS_JSON', '').strip()
    challenge = {'WWW-Authenticate': 'Basic realm="SlashDr review"', 'Cache-Control': 'no-store'}
    if protected and csv_mode and cloud:
        if os.environ.get('CLOUD_CSV_ENABLED') != 'true' or not account_json:
            return JSONResponse({'error': 'Configure CLOUD_CSV_ENABLED=true, named REVIEW_ACCOUNTS_JSON accounts and the persistent database before enabling Render CSV access.'}, status_code=503)
    if protected and account_json:
        try:
            accounts = parse_accounts(account_json)
        except AuthConfigError as error:
            return JSONResponse({'error': str(error)}, status_code=503)
        scoped_clinics = await run_in_threadpool(authenticate_account, request.headers.get('authorization', ''), accounts)
        if scoped_clinics is None:
            return JSONResponse({'error': 'Reviewer login required.'}, status_code=401, headers=challenge)
    elif protected:
        if csv_mode and (not REVIEW_USERNAME or not REVIEW_PASSWORD):
            return JSONResponse({'error': 'CSV mode requires reviewer credentials.'}, status_code=503)
        if REVIEW_PASSWORD:
            authenticated = False
            try:
                scheme, token = request.headers.get('authorization', '').split(' ', 1)
                if scheme.lower() == 'basic':
                    user, password = base64.b64decode(token, validate=True).decode('utf-8').split(':', 1)
                    user_ok = secrets.compare_digest(user.encode(), REVIEW_USERNAME.encode())
                    password_ok = secrets.compare_digest(password.encode(), REVIEW_PASSWORD.encode())
                    authenticated = user_ok and password_ok
            except (ValueError, UnicodeError, binascii.Error):
                pass
            if not authenticated:
                return JSONResponse({'error': 'Reviewer login required.'}, status_code=401, headers=challenge)
    # UI and Swagger are served from the same origin; external browser calls are not needed.
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.headers.get('host'):
        return JSONResponse({'error': 'Cross-origin requests are not allowed.'}, status_code=403)
    scope_token = REQUEST_CLINICS.set(scoped_clinics)
    try:
        response = await call_next(request)
    finally:
        REQUEST_CLINICS.reset(scope_token)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers['Server-Timing'] = f'app;dur={elapsed_ms:.1f}'
    logging.getLogger('uvicorn.error').info('request_completed method=%s path=%s status=%s duration_ms=%.1f', request.method, request.url.path, response.status_code, elapsed_ms)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path in {'/', '/app.js', '/style.css'}:
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, error: HTTPException):
    return JSONResponse({'error': str(error.detail)}, status_code=error.status_code, headers=error.headers)


@app.exception_handler(DataError)
async def data_error(request: Request, error: DataError):
    return JSONResponse({'error': str(error)}, status_code=400)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    # Do not echo submitted inputs or credentials in errors.
    return JSONResponse({'error': 'Invalid request. Use a valid patient ID, numeric Clinic ID for CSV mode, and a question between 1 and 2,000 characters.'}, status_code=422)


@app.get('/health', tags=['Health'])
def health():
    return {'status': 'ok'}


@app.get('/', include_in_schema=False)
def interface():
    return FileResponse(ROOT / 'static' / 'index.html')


@app.get('/app.js', include_in_schema=False)
def javascript():
    return FileResponse(ROOT / 'static' / 'app.js', media_type='text/javascript')


@app.get('/style.css', include_in_schema=False)
def stylesheet():
    return FileResponse(ROOT / 'static' / 'style.css', media_type='text/css')


@app.get('/api/status', tags=['Configuration'])
def status(clinic_id: str | None = None):
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    store = get_store()
    return {'configured': bool(key and key not in {'your_openai_api_key_here', 'replace_me'}),
            'model': os.environ.get('OPENAI_MODEL', 'gpt-4.1-mini'),
            'data_mode': 'csv' if store else 'synthetic',
            'patient_count': store.patient_count(clinic_id) if store and clinic_id else (0 if store else len(synthetic_patients())),
            'generation_enabled': bool(key and key not in {'your_openai_api_key_here', 'replace_me'}) and (not store or os.environ.get('ALLOW_EXTERNAL_PATIENT_DATA') == 'true')}


@app.get('/api/clinics', tags=['Patients'])
def clinics():
    store = get_store()
    return store.clinics() if store else []


@app.get('/api/patients', response_model=list[PatientSummary], tags=['Patients'])
def patients(clinic_id: str | None = None, search: str = '', limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    store = get_store()
    if store:
        return store.patients(clinic_id, search, limit, offset)
    return [{'patient_id': p['patient_id'], 'name': p['name']} for p in synthetic_patients()]


@app.get('/api/patient', tags=['Patients'])
def patient(id: str = Query(..., pattern=r'^(?:P\d{3}|DB-\d+)$', examples=['P010']), clinic_id: str | None = None):
    store = get_store()
    if store:
        return store.patient(id, clinic_id)
    try:
        return select_patient(synthetic_patients(), id)
    except AppError as error:
        raise HTTPException(404, str(error)) from None


@app.post('/api/generate', response_model=GenerateResponse, response_model_exclude_unset=True, tags=['Generation'])
def generate(body: GenerateRequest):
    # A sync endpoint runs in FastAPI's worker thread pool; the blocking API call
    # does not block the event loop or unrelated health/read requests.
    store = get_store()
    if store:
        selected = store.patient(body.patient_id, body.clinic_id, body.question)
    else:
        try:
            selected = select_patient(synthetic_patients(), body.patient_id)
        except AppError as error:
            raise HTTPException(404, str(error)) from None
    try:
        result = generate_answer(selected, body.question)
        if store:
            cited = set(result['source_ids'])
            result['source_records'] = [r for r in selected['records'] if r['record_id'] in cited]
            result['context_scope'] = selected['context_scope']
        return result
    except AppError as error:
        raise HTTPException(400, str(error)) from None
