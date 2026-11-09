// UI behavior checks with fictional records; no browser or external API required.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
  constructor() { this.children=[]; this.handlers={}; this._value=''; this.selectedIndex=-1; this.open=false; this.attributes={}; }
  get options() { return this.children; }
  get value() { return this.isSelect ? (this.children[this.selectedIndex]?.value || '') : this._value; }
  set value(value) { if(this.isSelect) this.selectedIndex=this.children.findIndex(x=>x.value===value); else this._value=value; }
  append(...items) { this.children.push(...items); if(this.isSelect && this.selectedIndex<0 && this.children.length) this.selectedIndex=0; }
  replaceChildren(...items) { this.children=[]; this.selectedIndex=-1; this.append(...items); }
  addEventListener(name, fn) { this.handlers[name]=fn; }
  setAttribute(key,value) {this.attributes[key]=value;} removeAttribute(key) {delete this.attributes[key];} focus() {}
  showModal() { this.open=true; } close() { this.open=false; }
}
const elements = new Map();
const element = id => { if(!elements.has(id)) elements.set(id,new Element()); return elements.get(id); };
element('patient').isSelect=true;
const ids=Array.from({length:105},(_,i)=>`P${i+1}`);
const context=vm.createContext({document:{getElementById:element,querySelectorAll:()=>[],createElement:()=>new Element(),createElementNS:()=>new Element()},AbortController,setTimeout,clearTimeout,console,
  fetch:async path=>{
    const url=new URL(path,'http://test'); let body;
    if(url.pathname==='/api/clinics') body=[{clinic_id:'13',name:'Clinic 13'}];
    else if(url.pathname==='/api/status') body={data_mode:'csv',generation_enabled:false,patient_count:105};
    else if(url.pathname==='/api/patients') body=ids.slice(Number(url.searchParams.get('offset')),Number(url.searchParams.get('offset'))+51).map(patient_id=>({patient_id}));
    else if(url.pathname==='/api/patient') body={patient_id:url.searchParams.get('id'),clinic_id:'13',name:'Fictional patient',records:[{record_id:'fixture',type:'profile',date:'2026-09-01'}]};
    else if(url.pathname==='/api/patient-info') body={patient_id:url.searchParams.get('id'),fields:{Name:'Fictional popup name'},note:'Test only'};
    else throw Error(path);
    return {ok:true,json:async()=>body};
  }
});
(async()=>{
  vm.runInContext(fs.readFileSync('static/app.js','utf8'),context);
  for(let i=0;i<12;i++) await new Promise(setImmediate);
  assert.equal(element('clinic-id').value,'13'); assert.equal(element('clinic-id').disabled,true);
  assert.equal(element('clinic-load').hidden,true); assert.equal(element('patient').value,'P1');
  assert.equal(element('patients-previous').disabled,true);
  await element('patients-next').handlers.click(); assert.equal(element('patient').value,'P2');
  await element('patients-previous').handlers.click(); assert.equal(element('patient').value,'P1');
  element('patient').selectedIndex=49; await element('patient').handlers.change();
  await element('patients-next').handlers.click(); assert.equal(element('patient').value,'P51');
  await element('patients-previous').handlers.click(); assert.equal(element('patient').value,'P50');
  await element('patient-info').handlers.click(); assert.equal(element('patient-dialog').open,true);
  assert.equal(element('patient-info-fields').children[1].textContent,'Fictional popup name');
  await element('patients-next').handlers.click(); assert.equal(element('patient-dialog').open,false);
  assert.equal(element('patient-info-fields').children.length,0);
  for(let i=0;i<54;i++) await element('patients-next').handlers.click();
  assert.equal(element('patient').value,'P105'); assert.equal(element('patients-next').disabled,true);
  const visit=(id,date)=>({record_id:`P1-appointments-${id}`,source_table:'appointments',type:'appointments',date,data:{id}});
  const bp=(id,date,answer,appointment_id,unit='mm.Hg')=>({record_id:`P1-vital_answers-${id}`,source_table:'vital_answers',type:'vital_answers',date,data:{answer,appointment_id,lookup_context:{question_id:{name:'BP',unit}}}});
  context.testRecords=[visit('1','2026-01-01'),visit('2','2026-01-02'),visit('3','2026-01-03'),bp('1','2026-01-01','120-80','1'),bp('2','2026-01-03','130/85','3')];
  vm.runInContext('renderOverview(testRecords)',context);
  assert.equal(element('latest-measurements').children.length,4);
  assert.equal(element('visit-timeline').children.length,3);
  const chart=element('trend-chart').children[0];
  assert.equal(chart.children.filter(x=>x.attributes.stroke==='#007b78').length,0,'Missing visit must break the connecting line');
  assert.equal(chart.children.filter(x=>x.attributes.role==='button').length,4,'Both BP components remain visible');
  chart.children.find(x=>x.attributes.role==='button').handlers.click();
  assert.equal(element('source-dialog').open,true);
  assert.equal(element('records').children[0].id,'record-P1-vital_answers-1');
  context.testRecords=[visit('1','2026-01-01'),visit('2','2026-01-01'),bp('1','2026-01-01','120-80','1'),bp('2','2026-01-01','125-82','1'),bp('3','not recorded','text','2'),bp('4','2026-01-01','130-80','2','unknown')];
  vm.runInContext('renderOverview(testRecords)',context);
  assert.equal(element('visit-timeline').children.length,2,'Two same-day appointments remain separate');
  assert.match(element('trend-note').textContent,/Only one recorded date/);
  assert.match(element('trend-note').textContent,/2 entry/);
  assert.equal(element('trend-table').children[0].children[1].children.length,4,'Unplottable and same-day entries retained');
  assert.equal(vm.runInContext('measurements(testRecords).length',context),4);
  assert.equal(vm.runInContext("validDate('2026-02-31')",context),null);
  vm.runInContext('clearOverview()',context);
  assert.equal(element('source-dialog').open,false);
  assert.equal(element('visit-timeline').children.length,0);
  console.log('Passed: trends, missing-reading gaps, separate same-day visits, repeated readings, unsupported units, source popup and patient clearing.');
  console.log('Passed: assigned clinic, sequential navigation, both page boundaries, last patient, popup and stale-detail clearing.');
})().catch(error=>{console.error(error);process.exitCode=1;});
