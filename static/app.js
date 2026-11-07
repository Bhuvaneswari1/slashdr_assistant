'use strict';
const $ = id => document.getElementById(id);
let dataMode = 'synthetic', clinicId = '', pageOffset = 0, searchVersion = 0, searchTimer;
let patientPage = [], hasNextPage = false, totalPatients = 0, listLoading = false, patientLoading = false;
let patients = [], selected = null, lastResult = null, configured = false, busy = false, selectionVersion = 0;
async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), path === '/api/generate' ? 90000 : 45000);
  try {
    const response = await fetch(path, {...options, signal: controller.signal});
    let body;
    try { body = await response.json(); }
    catch (error) { if (error.name === 'AbortError') throw error; throw new Error(`The server returned an unreadable response (HTTP ${response.status}). Refresh and check Render logs.`); }
    if (!response.ok) throw new Error(body.error || `Request failed (HTTP ${response.status}).`);
    return body;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('The request timed out. The server may still be processing it; check Render logs before retrying generation.');
    if (error instanceof TypeError) throw new Error('The browser lost its connection to the server. Refresh the page and check Render logs if it repeats.');
    throw error;
  } finally { clearTimeout(timer); }
}
function generationHelp() {
  $('generation-help').textContent = !configured ? (dataMode === 'csv' ? 'AI generation is disabled in the server settings. Patient records can still be reviewed.' : 'Add an API key in the server settings to enable AI generation.') : (!selected ? 'Select a patient to enable generation.' : '');
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
    const option = document.createElement('option'); option.value = p.patient_id; option.textContent = dataMode === 'csv' ? p.patient_id : `${p.patient_id} · ${p.name}`; $('patient').append(option);
  }
  if ([...$('patient').options].some(o => o.value === previous)) $('patient').value = previous;
  loadPatient();
}
async function loadPatient() {
  const version = ++selectionVersion;
  clearPatientDetails(); patientLoading = true;
  $('patient-info').disabled = true;
  selected = null; lastResult = null; $('context-scope').textContent = ''; $('result').hidden = true; $('records').replaceChildren(); $('profile').replaceChildren(); $('count').textContent = ''; message('Loading patient records…'); $('generate').disabled = true; generationHelp();
  updateNavigation();
  if (!$('patient').value) { patientLoading = false; message('No matching patients. Try another search.'); updateNavigation(); return; }
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
    $('generate').disabled = !configured || busy; generationHelp();
    $('patient-info').disabled = false;
    message('Patient records ready.');
  } catch (error) { if (version === selectionVersion) message(error.message, true); }
  finally { if (version === selectionVersion) {patientLoading = false; updateNavigation();} }
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
function clearPatientDetails() {
  $('patient-info-fields').replaceChildren(); $('patient-info-note').textContent = ''; $('patient-info-status').textContent = '';
  if ($('patient-dialog').open) $('patient-dialog').close();
}
function updateNavigation() {
  if (dataMode !== 'csv') return;
  const index = $('patient').selectedIndex;
  const unavailable = listLoading || patientLoading || !selected || index < 0;
  $('patients-previous').disabled = unavailable || (index === 0 && pageOffset === 0);
  $('patients-next').disabled = unavailable || (index === patientPage.length - 1 && !hasNextPage);
  $('patient-position').textContent = index < 0 || !patientPage.length ? '' : ($('search').value.trim() ? 'Exact patient search result' : `Patient ${pageOffset + index + 1}${totalPatients ? ` of ${totalPatients.toLocaleString()}` : ''}`);
}
async function searchCsvPatients(reset = false, selectLast = false) {
  const version = ++searchVersion;
  if (reset) pageOffset = 0;
  ++selectionVersion; selected = null; lastResult = null; listLoading = true;
  clearPatientDetails(); $('patient-info').disabled = true;
  $('result').hidden = true; $('generate').disabled = true;
  $('profile').replaceChildren(); $('records').replaceChildren(); $('context-scope').textContent = ''; $('count').textContent = '';
  if (!clinicId) {listLoading = false; updateNavigation(); return;}
  message('Loading patients for the selected clinic…'); updateNavigation();
  try {
    const list = await api(`/api/patients?clinic_id=${encodeURIComponent(clinicId)}&search=${encodeURIComponent($('search').value)}&offset=${pageOffset}&limit=51`);
    if (version !== searchVersion) return;
    hasNextPage = list.length > 50; patientPage = list.slice(0, 50);
    $('patient').replaceChildren();
    for (const p of patientPage) {
      const option = document.createElement('option'); option.value = p.patient_id; option.textContent = p.patient_id; $('patient').append(option);
    }
    if (patientPage.length) $('patient').selectedIndex = selectLast ? patientPage.length - 1 : 0;
    listLoading = false;
    await loadPatient();
  } catch (error) { if (version === searchVersion) message(error.message, true); }
  finally {if (version === searchVersion) {listLoading = false; updateNavigation();}}
}
async function navigatePatient(direction) {
  if (listLoading || patientLoading || !selected) return;
  const index = $('patient').selectedIndex + direction;
  if (index >= 0 && index < patientPage.length) {
    $('patient').selectedIndex = index; await loadPatient();
  } else if (direction > 0 && hasNextPage) {
    pageOffset += 50; await searchCsvPatients(false, false);
  } else if (direction < 0 && pageOffset > 0) {
    pageOffset = Math.max(0, pageOffset - 50); await searchCsvPatients(false, true);
  }
}
$('patient-info').addEventListener('click', async () => {
  if (!selected || patientLoading || listLoading) return;
  const id = selected.patient_id, version = selectionVersion;
  const popup = $('patient-dialog'); clearPatientDetails();
  $('patient-info-status').textContent = 'Loading patient details…'; popup.showModal();
  try {
    const result = await api(`/api/patient-info?id=${encodeURIComponent(id)}${dataMode === 'csv' ? `&clinic_id=${encodeURIComponent(clinicId)}` : ''}`);
    if (version !== selectionVersion || selected?.patient_id !== result.patient_id || !popup.open) return;
    for (const [label, value] of Object.entries(result.fields)) {
      const term = document.createElement('dt'); term.textContent = label;
      const detail = document.createElement('dd'); detail.textContent = value === null || value === '' ? 'Not documented / not available' : String(value);
      $('patient-info-fields').append(term, detail);
    }
    $('patient-info-note').textContent = result.note; $('patient-info-status').textContent = '';
  } catch (error) {if (version === selectionVersion && popup.open) $('patient-info-status').textContent = error.message;}
});
$('patient-dialog-close').addEventListener('click', () => $('patient-dialog').close());
$('patient-dialog').addEventListener('click', event => {
  if (event.target !== $('patient-dialog')) return;
  const bounds = $('patient-dialog').getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) $('patient-dialog').close();
});
$('clinic-id').addEventListener('input', () => {
  clinicId = ''; ++searchVersion; ++selectionVersion; selected = null; lastResult = null;
  clearPatientDetails(); $('patient-info').disabled = true; patientPage = []; updateNavigation();
  $('result').hidden = true; $('generate').disabled = true; generationHelp(); $('patient').replaceChildren();
  $('profile').replaceChildren(); $('records').replaceChildren(); $('context-scope').textContent = ''; $('count').textContent = '';
});
async function loadClinic() {
  const requestedClinic = $('clinic-id').value.trim();
  if (!/^\d+$/.test(requestedClinic)) { message('Enter a numeric Clinic ID.', true); return; }
  clinicId = requestedClinic; $('search').value = '';
  const button = $('clinic-load');
  button.disabled = true; button.setAttribute('aria-busy', 'true'); button.textContent = 'Loading patients…';
  try {
    await Promise.all([
      searchCsvPatients(true),
      api(`/api/status?clinic_id=${encodeURIComponent(requestedClinic)}`).then(status => {
        if (clinicId !== requestedClinic) return;
        configured = status.generation_enabled; totalPatients = status.patient_count; updateNavigation();
        $('status').textContent = `${status.patient_count.toLocaleString()} patients in clinic ${requestedClinic}. ${configured ? 'AI generation enabled.' : 'Record review available; AI generation disabled.'}`;
        $('generate').disabled = !configured || !selected || busy; generationHelp();
      }),
    ]);
  } catch (error) { if (clinicId === requestedClinic) message(error.message, true); }
  finally { button.disabled = false; button.removeAttribute('aria-busy'); button.textContent = 'Load clinic patients'; }
}
$('clinic-load').addEventListener('click', loadClinic);
$('patients-previous').addEventListener('click', () => navigatePatient(-1));
$('patients-next').addEventListener('click', () => navigatePatient(1));
(async () => {
  try {
    const [status, availableClinics] = await Promise.all([api('/api/status'), api('/api/clinics')]);
    dataMode = status.data_mode || 'synthetic';
    configured = status.generation_enabled ?? status.configured; generationHelp();
    if (dataMode === 'csv') {
      $('clinic-controls').hidden = false; $('patient-pages').hidden = false;
      $('search-label').textContent = 'Find by exact patient ID'; $('search').placeholder = 'For example P123 or 123';
      $('data-notice').textContent = 'Imported CSV patient records · Select an authorized Clinic ID · AI answers require clinician review';
      $('records-help').textContent = 'Open a source to inspect the imported CSV row. See the scope notes for retrieval limits.';
      $('status').textContent = 'Enter an authorized Clinic ID, then load its patients.';
      $('generate').disabled = true;
      for (const clinic of availableClinics) {
        const option = document.createElement('option'); option.value = clinic.clinic_id; option.textContent = clinic.name; $('clinic-options').append(option);
      }
      if (availableClinics.length === 1) {
        $('clinic-id').value = availableClinics[0].clinic_id;
        $('clinic-id').disabled = true; $('clinic-id').removeAttribute('list');
        $('clinic-load').hidden = true; $('clinic-help').hidden = false;
        $('clinic-help').textContent = 'Your assigned clinic is selected automatically.';
        await loadClinic();
      }
    } else {
      patients = await api('/api/patients');
      $('status').textContent = configured ? `${status.patient_count} synthetic patients · ${status.model} · Key configured (not verified)` : 'Records are available. To generate answers, add your API key to .env and restart.';
      filterPatients();
    }
  } catch (error) { message(error.message, true); }
})();
