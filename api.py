"""FastAPI entry point: python3 -m uvicorn api:app --port 8000."""
import base64
import binascii
import os
import secrets
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from core import ROOT, AppError, generate_answer, load_env, load_patients, select_patient

load_env()
PATIENTS = load_patients()
REVIEW_USERNAME = os.environ.get('REVIEW_USERNAME', '')
REVIEW_PASSWORD = os.environ.get('REVIEW_PASSWORD', '')
if bool(REVIEW_USERNAME) != bool(REVIEW_PASSWORD):
    raise RuntimeError('Set both REVIEW_USERNAME and REVIEW_PASSWORD, or leave both unset for local development.')
if os.environ.get('RENDER') == 'true' and not REVIEW_PASSWORD:
    raise RuntimeError('Set REVIEW_USERNAME and REVIEW_PASSWORD in Render before starting the review service.')

app = FastAPI(
    title='SlashDr Patient Records API', version='1.1.0',
    description='Read-only synthetic patient review demo. Answers require clinician verification. '
                'The OpenAI key stays on the server. Reviewer credentials, if configured, use HTTP Basic authentication.',
)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    patient_id: str = Field(pattern=r'^P\d{3}$', examples=['P010'])
    question: str = Field(min_length=1, max_length=2000,
                          examples=['Summarise this patient before the next visit.'])


class GenerateResponse(BaseModel):
    patient_id: str
    answer: str
    source_ids: list[str]
    missing_information: list[str]


class PatientSummary(BaseModel):
    patient_id: str
    name: str


@app.middleware('http')
async def review_controls(request: Request, call_next):
    if REVIEW_PASSWORD and request.url.path != '/health':
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
            return JSONResponse({'error': 'Reviewer login required.'}, status_code=401,
                                headers={'WWW-Authenticate': 'Basic realm="SlashDr review"', 'Cache-Control': 'no-store'})
    # UI and Swagger are served from the same origin; external browser calls are not needed.
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.headers.get('host'):
        return JSONResponse({'error': 'Cross-origin requests are not allowed.'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path in {'/', '/app.js', '/style.css'}:
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, error: HTTPException):
    return JSONResponse({'error': str(error.detail)}, status_code=error.status_code, headers=error.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    # Do not echo submitted inputs or credentials in errors.
    return JSONResponse({'error': 'Invalid request. Use a patient ID such as P010 and a question between 1 and 2,000 characters.'}, status_code=422)


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
def status():
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    return {'configured': bool(key and key not in {'your_openai_api_key_here', 'replace_me'}),
            'model': os.environ.get('OPENAI_MODEL', 'gpt-4.1-mini'), 'patient_count': len(PATIENTS)}


@app.get('/api/patients', response_model=list[PatientSummary], tags=['Patients'])
def patients():
    return [{'patient_id': p['patient_id'], 'name': p['name']} for p in PATIENTS]


@app.get('/api/patient', tags=['Patients'])
def patient(id: str = Query(..., pattern=r'^P\d{3}$', examples=['P010'])):
    try:
        return select_patient(PATIENTS, id)
    except AppError as error:
        raise HTTPException(404, str(error)) from None


@app.post('/api/generate', response_model=GenerateResponse, tags=['Generation'])
def generate(body: GenerateRequest):
    # A sync endpoint runs in FastAPI's worker thread pool; the blocking API call
    # does not block the event loop or unrelated health/read requests.
    try:
        selected = select_patient(PATIENTS, body.patient_id)
    except AppError as error:
        raise HTTPException(404, str(error)) from None
    try:
        return generate_answer(selected, body.question)
    except AppError as error:
        raise HTTPException(400, str(error)) from None
