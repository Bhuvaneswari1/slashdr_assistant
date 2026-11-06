'use strict';
const $ = id => document.getElementById(id);
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
  selected = null; lastResult = null; $('result').hidden = true; $('records').replaceChildren(); $('profile').replaceChildren(); $('count').textContent = ''; message(''); $('generate').disabled = true;
  if (!$('patient').value) { message('No matching patients. Try another search.'); return; }
  try {
    const patient = await api(`/api/patient?id=${encodeURIComponent($('patient').value)}`);
    if (version !== selectionVersion) return;
    selected = patient;
    const title = document.createElement('strong'); title.textContent = patient.name;
    const info = document.createElement('p'); info.textContent = `${patient.patient_id} · ${patient.records[0].age} years · ${patient.clinic_id}`;
    const condition = document.createElement('p'); condition.textContent = `Recorded condition: ${patient.records[0].recorded_condition}`;
    $('profile').append(title, info, condition);
    $('count').textContent = `${patient.records.length} RECORDS`;
    $('records').replaceChildren(...patient.records.map(recordElement));
    $('generate').disabled = !configured || busy;
  } catch (error) { if (version === selectionVersion) message(error.message, true); }
}
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => { $('question').value = button.dataset.question; $('question').focus(); }));
$('search').addEventListener('input', filterPatients);
$('patient').addEventListener('change', loadPatient);
$('ask').addEventListener('submit', async event => {
  event.preventDefault(); if (!selected || busy || !configured) return;
  const patientId = selected.patient_id, version = selectionVersion, question = $('question').value;
  busy = true; $('generate').disabled = true; $('result').hidden = true; lastResult = null;

  message('Reading the selected records and generating an answer…');
  try {
    const result = await api('/api/generate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({patient_id: patientId, question})});
    if (version !== selectionVersion || result.patient_id !== selected?.patient_id) return;
    lastResult = {...result, question};
    $('answer').textContent = result.answer;
    $('missing').textContent = result.missing_information.length ? `Missing information: ${result.missing_information.join('; ')}` : '';
    $('sources').replaceChildren();
    for (const id of result.source_ids) {
      const a = document.createElement('a'); a.href = `#record-${id}`; a.textContent = id;
      a.addEventListener('click', () => { $(`record-${id}`).open = true; }); $('sources').append(a);
    }
    if (!result.source_ids.length) $('sources').textContent = 'No supporting records cited.';
    $('result').hidden = false; message('Generation complete. Verify the answer against the sources before use.');
  } catch (error) { if (version === selectionVersion) message(error.message, true); }
  finally { busy = false; $('generate').disabled = !configured || !selected; }
});
$('download').addEventListener('click', () => {
  if (!lastResult) return;
  const blob = new Blob([`SYNTHETIC DEMO — AI DRAFT FOR REVIEW\n\n${JSON.stringify(lastResult, null, 2)}`], {type: 'text/plain'});
  const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = `slashdr-${lastResult.patient_id}-draft.txt`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
(async () => {
  try {
    const [status, list] = await Promise.all([api('/api/status'), api('/api/patients')]);
    configured = status.configured; patients = list;
    $('status').textContent = configured ? `${status.patient_count} synthetic patients · ${status.model} · Key configured (not verified)` : 'Records are available. To generate answers, add your API key to .env and restart.';
    filterPatients();
  } catch (error) { message(error.message, true); }
})();
