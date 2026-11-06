'use strict';
const $ = id => document.getElementById(id);
let dataMode = 'synthetic', clinicId = '', pageOffset = 0, searchVersion = 0, searchTimer;
let patients = [], selected = null, lastResult = null, configured = false, busy = false, selectionVersion = 0;
async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Request failed.');
  return body;
}
function message(text, error = false) { $('message').textContent = text; $('message').className = error ? 'error' : ''; }
function recordElement(record) {
  const detail = document.createElement('details'); detail.id = `record-${record.record_id}`;
  const summary = document.createElement('summary');
  summary.textContent = `${record.date} · ${record.type.replaceAll('_', ' ')} · ${record.record_id}`;
  const pre = document.createElement('pre'); pre.textContent = JSON.stringify(record, null, 2);
  detail.append(summary, pre); return detail;
}
function filterPatients() {
  if (dataMode === 'csv') {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => searchCsvPatients(true), 250);
    return;
  }
  const query = $('search').value.toLowerCase();
  const previous = $('patient').value;
  $('patient').replaceChildren();
  for (const p of patients.filter(p => `${p.patient_id} ${p.name}`.toLowerCase().includes(query))) {
    const option = document.createElement('option'); option.value = p.patient_id; option.textContent = `${p.patient_id} · ${p.name}`; $('patient').append(option);
  }
  if ([...$('patient').options].some(o => o.value === previous)) $('patient').value = previous;
  loadPatient();
}
async function loadPatient() {
  const version = ++selectionVersion;
  selected = null; lastResult = null; $('context-scope').textContent = ''; $('result').hidden = true; $('records').replaceChildren(); $('profile').replaceChildren(); $('count').textContent = ''; message(''); $('generate').disabled = true;
  if (!$('patient').value) { message('No matching patients. Try another search.'); return; }
  try {
    const patient = await api(`/api/patient?id=${encodeURIComponent($('patient').value)}${dataMode === 'csv' ? `&clinic_id=${encodeURIComponent(clinicId)}` : ''}`);
    if (version !== selectionVersion) return;
    selected = patient;
    const title = document.createElement('strong'); title.textContent = patient.name;
    const info = document.createElement('p'); info.textContent = `${patient.patient_id} · ${patient.records[0]?.age ?? 'Age not recorded'} ${patient.records[0]?.data?.age_type || (dataMode === 'synthetic' ? 'years' : '(source age unit)')} · Clinic ${patient.clinic_id}`;
    const condition = document.createElement('p'); condition.textContent = `Recorded condition: ${patient.records[0].recorded_condition}`;
    $('profile').append(title, info, condition);
    $('count').textContent = `${patient.records.length} RECORDS`;
    $('records').replaceChildren(...patient.records.map(recordElement));
    $('context-scope').textContent = patient.context_scope?.notes?.join(' ') || '';
    $('generate').disabled = !configured || busy;
  } catch (error) { if (version === selectionVersion) message(error.message, true); }
}
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => { $('question').value = button.dataset.question; $('question').focus(); }));
$('search').addEventListener('input', filterPatients);
$('patient').addEventListener('change', loadPatient);
$('ask').addEventListener('submit', async event => {
  event.preventDefault(); if (!selected || busy || !configured) return;
  const patientId = selected.patient_id, version = selectionVersion, question = $('question').value;
  const requestClinic = clinicId;
  busy = true; $('generate').disabled = true; $('result').hidden = true; lastResult = null;

  message('Reading the selected records and generating an answer…');
  try {
    const result = await api('/api/generate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({patient_id: patientId, question, ...(dataMode === 'csv' ? {clinic_id: requestClinic} : {})})});
    if (version !== selectionVersion || result.patient_id !== selected?.patient_id) return;
    lastResult = {...result, question, ...(dataMode === 'csv' ? {clinic_id: requestClinic} : {})};
    for (const record of result.source_records || []) {
      if (!$(`record-${record.record_id}`)) $('records').append(recordElement(record));
    }
    if (result.context_scope) {
      $('context-scope').textContent = result.context_scope.notes.join(' ');
      $('count').textContent = `${$('records').children.length} RECORDS`;
    }
    $('answer').textContent = result.answer;
    $('missing').textContent = result.missing_information.length ? `Missing information: ${result.missing_information.join('; ')}` : '';
    $('sources').replaceChildren();
    for (const id of result.source_ids) {
      const a = document.createElement('a'); a.href = `#record-${id}`; a.textContent = id;
      a.addEventListener('click', () => { const target = $(`record-${id}`); if (target) target.open = true; }); $('sources').append(a);
    }
    if (!result.source_ids.length) $('sources').textContent = 'No supporting records cited.';
    $('result').hidden = false; message('Generation complete. Verify the answer against the sources before use.');
  } catch (error) { if (version === selectionVersion) message(error.message, true); }
  finally { busy = false; $('generate').disabled = !configured || !selected; }
});
$('download').addEventListener('click', () => {
  if (!lastResult) return;
  const blob = new Blob([`${dataMode === 'csv' ? 'IMPORTED PATIENT RECORDS' : 'SYNTHETIC DEMO'} — AI DRAFT FOR REVIEW\n\n${JSON.stringify(lastResult, null, 2)}`], {type: 'text/plain'});
  const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = `slashdr-${lastResult.patient_id}-draft.txt`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
async function searchCsvPatients(reset = false) {
  const version = ++searchVersion;
  if (reset) pageOffset = 0;
  ++selectionVersion; selected = null; lastResult = null;
  $('result').hidden = true; $('generate').disabled = true;
  $('profile').replaceChildren(); $('records').replaceChildren(); $('context-scope').textContent = ''; $('count').textContent = '';
  if (!clinicId) return;
  try {
    const list = await api(`/api/patients?clinic_id=${encodeURIComponent(clinicId)}&search=${encodeURIComponent($('search').value)}&offset=${pageOffset}&limit=50`);
    if (version !== searchVersion) return;
    $('patient').replaceChildren();
    for (const p of list) {
      const option = document.createElement('option'); option.value = p.patient_id; option.textContent = `${p.patient_id} · ${p.name}`; $('patient').append(option);
    }
    $('patients-previous').disabled = pageOffset === 0;
    $('patients-next').disabled = list.length < 50;
    await loadPatient();
  } catch (error) { if (version === searchVersion) message(error.message, true); }
}
$('clinic-id').addEventListener('input', () => {
  clinicId = ''; ++searchVersion; ++selectionVersion; selected = null; lastResult = null;
  $('result').hidden = true; $('generate').disabled = true; $('patient').replaceChildren();
  $('profile').replaceChildren(); $('records').replaceChildren(); $('context-scope').textContent = ''; $('count').textContent = '';
});
$('clinic-load').addEventListener('click', async () => {
  clinicId = $('clinic-id').value.trim(); $('search').value = '';
  try {
    const status = await api(`/api/status?clinic_id=${encodeURIComponent(clinicId)}`);
    configured = status.generation_enabled;
    $('status').textContent = `${status.patient_count} patients in clinic ${clinicId}. ${configured ? 'External generation enabled.' : 'Record review enabled. External generation disabled.'}`;
    await searchCsvPatients(true);
  } catch (error) { message(error.message, true); }
});
$('patients-previous').addEventListener('click', () => {pageOffset = Math.max(0, pageOffset - 50); searchCsvPatients();});
$('patients-next').addEventListener('click', () => {pageOffset += 50; searchCsvPatients();});
(async () => {
  try {
    const status = await api('/api/status');
    dataMode = status.data_mode || 'synthetic';
    configured = status.generation_enabled ?? status.configured;
    if (dataMode === 'csv') {
      $('clinic-controls').hidden = false; $('patient-pages').hidden = false;
      $('search-label').textContent = 'Find by exact patient ID'; $('search').placeholder = 'For example DB-123 or 123';
      $('data-notice').textContent = 'Imported CSV patient records · Select an authorized Clinic ID · AI answers require clinician review';
      $('records-help').textContent = 'Open a source to inspect the imported CSV row. See the scope notes for retrieval limits.';
      $('status').textContent = 'Enter an authorized Clinic ID, then load its patients.';
      $('generate').disabled = true;
      const clinics = await api('/api/clinics');
      for (const clinic of clinics) {
        const option = document.createElement('option'); option.value = clinic.clinic_id; option.textContent = clinic.name; $('clinic-options').append(option);
      }
    } else {
      patients = await api('/api/patients');
      $('status').textContent = configured ? `${status.patient_count} synthetic patients · ${status.model} · Key configured (not verified)` : 'Records are available. To generate answers, add your API key to .env and restart.';
      filterPatients();
    }
  } catch (error) { message(error.message, true); }
})();
