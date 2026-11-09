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
// Patient overview uses recorded values only; no LLM, interpolation or clinical thresholds.
let overviewRecords = new Map();
let trendMetric = 'bp';
const metricDefinitions = {
  bp: {label: 'Blood pressure', unit: 'mmHg', aliases: ['bp', 'blood pressure'], units: ['mmhg', 'mm.hg'], series: ['Systolic', 'Diastolic']},
  hr: {label: 'Heart rate', unit: 'BPM', aliases: ['hr', 'heart rate', 'pulse'], units: ['bpm', 'beats/min'], series: ['Heart rate']},
  spo2: {label: 'Oxygen saturation', unit: '%', aliases: ['spo2', 'oxygen saturation'], units: ['%'], series: ['SpO₂']},
  weight: {label: 'Weight', unit: 'kg', aliases: ['weight', 'body weight'], units: ['kg'], series: ['Weight']},
};
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function sourceButton(record, label = 'View source') {
  const button = node('button', label, 'source-button'); button.type = 'button';
  button.addEventListener('click', () => openSource(record.record_id)); return button;
}
function openSource(id) {
  const record = overviewRecords.get(id); if (!record) return;
  $('source-title').textContent = `Source record · ${id}`;
  $('records').replaceChildren(recordElement(record));
  $('records').children[0].open = true;
  if (!$('source-dialog').open) $('source-dialog').showModal();
}
function closeSource() { if ($('source-dialog').open) $('source-dialog').close(); }
function clearOverview() {
  overviewRecords.clear(); closeSource();
  for (const id of ['latest-measurements', 'trend-chart', 'trend-table', 'visit-timeline', 'records']) $(id).replaceChildren();
  $('trend-note').textContent = 'Select a patient to view recorded measurements.';
}
function validDate(value) {
  const date = String(value || '').slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const time = Date.parse(date + 'T00:00:00Z');
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === date ? date : null;
}
function measurements(records) {
  const result = [];
  const push = (record, key, raw, unit, date) => {
    if (raw === null || raw === undefined || String(raw).trim() === '') return;
    const definition = metricDefinitions[key], text = String(raw).trim();
    const supportedUnit = definition.units.includes(String(unit || '').toLowerCase().replace(/\s+/g, ''));
    const match = key === 'bp' ? text.match(/^(\d+(?:\.\d+)?)\s*[-/]\s*(\d+(?:\.\d+)?)$/) : text.match(/^(\d+(?:\.\d+)?)$/);
    const values = match && supportedUnit ? match.slice(1).map(Number) : null;
    result.push({key, raw: text, unit: unit || 'Unit not recorded', date: validDate(date), values, record});
  };
  for (const record of records) {
    if (record.type === 'vitals' && !record.source_table) {
      if (record.systolic != null && record.diastolic != null) push(record, 'bp', `${record.systolic}/${record.diastolic}`, record.bp_unit, record.date);
      push(record, 'weight', record.weight, record.weight_unit, record.date);
    }
    if (record.source_table !== 'vital_answers') continue;
    const data = record.data || {}, question = data.lookup_context?.question_id;
    const label = String(question?.name || '').trim().toLowerCase();
    for (const [key, definition] of Object.entries(metricDefinitions)) {
      if (definition.aliases.includes(label)) push(record, key, data.answer ?? data.value, question.unit, record.date);
    }
  }
  return result.sort((a,b) => (a.date || '').localeCompare(b.date || '') || a.record.record_id.localeCompare(b.record.record_id));
}
function renderOverview(records) {
  overviewRecords = new Map(records.map(record => [record.record_id, record]));
  const readings = measurements(records);
  $('count').textContent = `${overviewRecords.size} SOURCE ENTRIES`;
  $('latest-measurements').replaceChildren();
  for (const [key, definition] of Object.entries(metricDefinitions)) {
    const dated = readings.filter(reading => reading.key === key && reading.date);
    const latestDate = dated.at(-1)?.date;
    const latest = dated.filter(reading => reading.date === latestDate);
    const card = node('article', undefined, 'measurement-card'); card.append(node('h3', definition.label));
    if (!latest.length) card.append(node('p', 'No dated reading available', 'muted'));
    else {
      for (const reading of latest) {
        card.append(sourceButton(reading.record, `${reading.raw} ${reading.unit}`));
      }
      card.append(node('p', `${latestDate}${latest.length > 1 ? ' · Multiple entries on this date' : ''}`, 'muted'));
    }
    $('latest-measurements').append(card);
  }
  renderTrend(); renderTimeline(records);
}
function renderTrend() {
  const definition = metricDefinitions[trendMetric];
  const readings = measurements([...overviewRecords.values()]).filter(reading => reading.key === trendMetric);
  const points = readings.filter(reading => reading.date && reading.values);
  $('trend-chart').replaceChildren(); $('trend-table').replaceChildren();
  const dates = [...new Set(points.map(reading => reading.date))];
  const excluded = readings.length - points.length;
  $('trend-note').textContent = (!points.length ? 'No dated numeric readings with supported units are available for this measurement.' : dates.length === 1 ? 'Only one recorded date—trend unavailable. All readings from that date are retained.' : 'Recorded values over time. Gaps remain where a retrieved visit has no matching reading. Lines do not imply continuous monitoring.') + (excluded ? ` ${excluded} entry/entries cannot be plotted; inspect the table for missing dates, unsupported units or nonnumeric values.` : '') + ' Dates may be inherited from appointments; source details identify the date basis.';
  if (points.length) {
    const svgNode = (tag, attributes, text) => {
      const item = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [key,value] of Object.entries(attributes)) item.setAttribute(key, String(value));
      if (text !== undefined) item.textContent = text; return item;
    };
    const svg = svgNode('svg', {viewBox: '0 0 760 290', role: 'img', 'aria-label': `${definition.label} in ${definition.unit}. Exact values and source buttons follow in the table.`});
    const allDates = [...new Set([...dates, ...[...overviewRecords.values()].filter(r => r.source_table === 'appointments').map(r => validDate(r.date)).filter(Boolean)])].sort();
    const first = Date.parse(allDates[0]), last = Date.parse(allDates.at(-1));
    const values = points.flatMap(p => p.values), low = Math.min(...values), high = Math.max(...values), padding = Math.max((high-low)*.15, 1);
    const x = date => first === last ? 410 : 75 + (Date.parse(date)-first)/(last-first)*620;
    const y = value => 230 - (value-low+padding)/(high-low+padding*2)*195;
    for (let tick=0; tick<5; tick++) {
      const value = low-padding+(high-low+padding*2)*tick/4, position=y(value);
      svg.append(svgNode('line', {x1:65,x2:715,y1:position,y2:position,stroke:'#dbe6e7'}), svgNode('text', {x:55,y:position+4,'text-anchor':'end',fill:'#55717a','font-size':12}, String(Number(value.toFixed(1)))));
    }
    svg.append(svgNode('text',{x:65,y:18,fill:'#102e40','font-size':12},definition.unit));
    const colors=['#007b78','#935d9d'];
    for (let series=0; series<definition.series.length; series++) {
      // Connect only consecutive available dates with exactly one reading each.
      let previous=null;
      for (const date of allDates) {
        const sameDate=points.filter(p=>p.date===date);
        if (sameDate.length!==1) {previous=null; continue;}
        const current=sameDate[0];
        if (previous) svg.append(svgNode('line',{x1:x(previous.date),y1:y(previous.values[series]),x2:x(date),y2:y(current.values[series]),stroke:colors[series],'stroke-width':2}));
        previous=current;
      }
      for (const point of points) {
        const mark=svgNode('circle',{cx:x(point.date),cy:y(point.values[series]),r:5,fill:colors[series],tabindex:0,role:'button','aria-label':`${point.date}: ${definition.series[series]} ${point.values[series]} ${definition.unit}. Open source ${point.record.record_id}`});
        mark.append(svgNode('title',{},`${point.date} · ${point.raw} ${point.unit} · ${point.record.record_id}`));
        mark.addEventListener('click',()=>openSource(point.record.record_id));
        mark.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openSource(point.record.record_id);}}); svg.append(mark);
      }
    }
    const labels=allDates.length<=4?allDates:[allDates[0],allDates.at(-1)];
    for (const date of labels) svg.append(svgNode('text',{x:x(date),y:260,'text-anchor':'middle',fill:'#55717a','font-size':12},date));
    $('trend-chart').append(svg);
    $('trend-chart').append(node('p', definition.series.join(' / ') + (trendMetric==='bp'?' · Teal: systolic · Purple: diastolic':''), 'muted'));
  }
  if (readings.length) {
    const table=node('table'), head=node('thead'), heading=node('tr');
    for(const label of ['Date shown','Recorded value','Source']) heading.append(node('th',label)); head.append(heading);table.append(head);
    const body=node('tbody');
    for(const reading of readings) {
      const row=node('tr'), source=node('td');source.append(sourceButton(reading.record));
      row.append(node('td',reading.date || 'Not recorded'),node('td',`${reading.raw} ${reading.unit}`),source);body.append(row);
    }
    table.append(body);$('trend-table').append(table);
  }
}
function recordDescription(record) {
  const data=record.data || record, lookup=data.lookup_context || {};
  const label=lookup.question_id?.name || lookup.complaint_id?.name || lookup.pharma_generic_id?.name || lookup.pharma_generic_id?.generic_names?.name || record.test || record.drug;
  const value=data.answer ?? data.value ?? data.text ?? data.summary ?? data.name ?? data.title;
  if (label && value != null) return `${label}: ${value}${lookup.question_id?.unit ? ' '+lookup.question_id.unit : ''}`;
  if (label) return String(label);
  if (value != null && String(value).trim()) return String(value);
  return `Recorded entry · ${record.source_id || record.record_id}`;
}
function renderTimeline(records) {
  $('visit-timeline').replaceChildren();
  const groups=new Map();
  const appointments=new Map(records.filter(r=>r.source_table==='appointments').map(r=>[String(r.data.id),r]));
  for(const record of records) {
    if(record.type==='profile' || record.source_table==='people') continue;
    const appointmentId=record.source_table==='appointments'?String(record.data.id):record.data?.appointment_id;
    const key=appointmentId?`appointment-${appointmentId}`:record.encounter_id?`encounter-${record.encounter_id}`:`dated-${validDate(record.date)||'unknown'}`;
    if(!groups.has(key)) {
      const appointment=appointments.get(String(appointmentId));
      groups.set(key,{date:validDate(appointment?.date || record.date),appointmentId,records:[],visit:!!appointmentId || !!record.encounter_id});
    }
    groups.get(key).records.push(record);
  }
  for(const group of [...groups.values()].sort((a,b)=>(b.date||'').localeCompare(a.date||'') || String(a.appointmentId||'').localeCompare(String(b.appointmentId||'')))) {
    const detail=node('details',undefined,'visit-card'),summary=node('summary',`${group.date || 'Date not recorded'} · ${group.visit?'Visit':'Dated records (visit not linked)'}${group.appointmentId?' '+group.appointmentId:''} · ${group.records.length} entries`);detail.append(summary);
    const categories=new Map();
    for(const record of group.records) {
      if(record.source_table==='appointments') {detail.append(sourceButton(record,'Appointment source'));continue;}
      const type=record.source_table || record.type;
      const category=type==='vital_answers'||type==='vitals'?'Vitals':type==='symptoms_answers'||type==='complaint_answers'?'Symptoms':type==='prescriptions'||type==='medication'?'Prescriptions':type==='diagnosis_answers'||type==='standing_diagnoses'?'Diagnoses':type==='pdfs'||type==='pdf_patients'||type==='radiology_report'?'Reports':type==='person_states'?'Workflow status':'Notes & other records';
      if(!categories.has(category)) categories.set(category,[]);categories.get(category).push(record);
    }
    for(const [label,entries] of categories) {
      detail.append(node('h3',label));const list=node('ul',undefined,'visit-entries');
      for(const record of entries) {
        const li=node('li');li.append(node('span',recordDescription(record)),node('small',`${record.date || 'Date not recorded'} · ${record.date_basis || 'Recorded date'}`),sourceButton(record));list.append(li);
      }
      detail.append(list);
    }
    $('visit-timeline').append(detail);
  }
  if(!groups.size) $('visit-timeline').append(node('p','No visit or dated records are available in the retrieved scope.','muted'));
}
$('trend-metric').addEventListener('change',()=>{trendMetric=$('trend-metric').value;renderTrend();});
$('source-close').addEventListener('click',closeSource);
$('source-dialog').addEventListener('click',event=>{
  if(event.target!==$('source-dialog'))return;
  const bounds=$('source-dialog').getBoundingClientRect();
  if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)closeSource();
});

function filterPatients() {
  if (dataMode === 'csv') {
    clearTimeout(searchTimer);
    ++searchVersion; ++selectionVersion; selected = null; lastResult = null;
    patientLoading = false; listLoading = false;
    clearPatientDetails(); clearOverview(); $('profile').replaceChildren(); $('count').textContent = ''; $('context-scope').textContent = '';
    $('result').hidden = true; $('generate').disabled = true; $('patient-info').disabled = true;
    $('patient').disabled = true; generationHelp(); updateNavigation();
    $('search-status').textContent = 'Searching the selected clinic…';
    searchTimer = setTimeout(() => searchCsvPatients(true), 400);
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
  selected = null; lastResult = null; $('context-scope').textContent = ''; $('result').hidden = true; clearOverview(); $('profile').replaceChildren(); $('count').textContent = ''; message('Loading patient records…'); $('generate').disabled = true; generationHelp();
  updateNavigation();
  if (!$('patient').value) { patientLoading = false; message(dataMode === 'csv' ? 'Select an available patient in this clinic to continue.' : 'No matching patients. Try another search.'); updateNavigation(); return; }
  try {
    const patient = await api(`/api/patient?id=${encodeURIComponent($('patient').value)}${dataMode === 'csv' ? `&clinic_id=${encodeURIComponent(clinicId)}` : ''}`);
    if (version !== selectionVersion) return;
    selected = patient;
    const title = document.createElement('strong'); title.textContent = patient.name;
    const info = document.createElement('p'); info.textContent = `${patient.patient_id} · ${patient.records[0]?.age ?? 'Age not recorded'} ${patient.records[0]?.data?.age_type || (dataMode === 'synthetic' ? 'years' : '(source age unit)')} · Clinic ${patient.clinic_id}`;
    const condition = document.createElement('p'); condition.textContent = `Recorded condition: ${patient.records[0].recorded_condition}`;
    $('profile').append(title, info, condition);
    renderOverview(patient.records);
    $('context-scope').textContent = patient.context_scope?.notes?.join(' ') || '';
    $('generate').disabled = !configured || busy; generationHelp();
    $('patient-info').disabled = false;
    message('Patient records ready.');
  } catch (error) { if (version === selectionVersion) message(error.message, true); }
  finally { if (version === selectionVersion) {patientLoading = false; updateNavigation();} }
}
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => { $('question').value = button.dataset.question; $('question').focus(); }));
$('search').addEventListener('input', filterPatients);
$('patient-search').addEventListener('submit', event => {
  event.preventDefault(); clearTimeout(searchTimer);
  if (dataMode === 'csv') return searchCsvPatients(true);
  filterPatients();
});
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
    renderOverview([...overviewRecords.values(), ...(result.source_records || [])].filter((record, index, records) => records.findIndex(item => item.record_id === record.record_id) === index));
    $('context-scope').textContent = [...(selected.context_scope?.notes || []), 'The overview combines retrieved patient records and additional answer sources. An individual answer may use a narrower date-filtered subset.'].join(' ');
    $('answer').textContent = result.answer;
    $('missing').textContent = result.missing_information.length ? `Missing information: ${result.missing_information.join('; ')}` : '';
    $('sources').replaceChildren();
    for (const id of result.source_ids) {
      const a = document.createElement('a'); a.href = `#record-${id}`; a.textContent = id;
      a.addEventListener('click', event => { event.preventDefault(); openSource(id); }); $('sources').append(a);
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
  $('profile').replaceChildren(); clearOverview(); $('context-scope').textContent = ''; $('count').textContent = '';
  if (!clinicId) {listLoading = false; $('search-status').textContent = 'Select a clinic before searching.'; updateNavigation(); return;}
  const query = $('search').value.trim();
  if (query && !/^(?:P)?\d+$/i.test(query)) {
    $('patient').replaceChildren(); $('patient').disabled = true; listLoading = false;
    $('search-status').textContent = 'Enter P followed by digits (for example P11), or the numeric ID alone. No spaces or hyphens.';
    message('Enter a valid patient ID to continue.', true); updateNavigation(); return;
  }
  $('search-status').textContent = 'Searching the selected clinic…';
  message('Loading patients for the selected clinic…'); updateNavigation();
  try {
    const list = await api(`/api/patients?clinic_id=${encodeURIComponent(clinicId)}&search=${encodeURIComponent($('search').value)}&offset=${pageOffset}&limit=51`);
    if (version !== searchVersion) return;
    hasNextPage = list.length > 50; patientPage = list.slice(0, 50);
    $('patient').replaceChildren();
    for (const p of patientPage) {
      const option = document.createElement('option'); option.value = p.patient_id; option.textContent = p.patient_id; $('patient').append(option);
    }
    $('patient').disabled = !patientPage.length;
    if (patientPage.length) $('patient').selectedIndex = selectLast ? patientPage.length - 1 : 0;
    else {
      const empty = document.createElement('option'); empty.value = ''; empty.textContent = 'No patient found in this clinic'; $('patient').append(empty);
    }
    $('search-status').textContent = query
      ? (patientPage.length ? `Found ${patientPage[0].patient_id} in Clinic ${clinicId}.` : `No patient with ID ${query.toUpperCase().startsWith('P') ? query.toUpperCase() : 'P' + query} is available in Clinic ${clinicId}. IDs can have gaps. Empty the search field to browse available patients.`)
      : (patientPage.length ? 'Choose a patient below, or enter an exact ID above.' : 'No patients are available in this clinic.');
    listLoading = false;
    await loadPatient();
  } catch (error) { if (version === searchVersion) {message(error.message, true); $('search-status').textContent = 'Patient search failed. Please retry.';} }
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
  clinicId = ''; clearTimeout(searchTimer); $('search-status').textContent = ''; ++searchVersion; ++selectionVersion; selected = null; lastResult = null;
  clearPatientDetails(); $('patient-info').disabled = true; patientPage = []; updateNavigation();
  $('result').hidden = true; $('generate').disabled = true; generationHelp(); $('patient').replaceChildren();
  $('profile').replaceChildren(); clearOverview(); $('context-scope').textContent = ''; $('count').textContent = '';
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
      $('search-label').textContent = 'Find by exact patient ID'; $('search').placeholder = 'For example P11 or 11';
      $('data-notice').textContent = 'Imported CSV patient records · Select an authorized Clinic ID · AI answers require clinician review';
      $('records-help').textContent = 'Explore available measurements and visits. Click a value or source link to inspect the original entry. This overview covers retrieved records only.';
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
