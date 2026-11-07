// UI behavior checks with fictional records; no browser or external API required.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
  constructor() { this.children=[]; this.handlers={}; this._value=''; this.selectedIndex=-1; this.open=false; }
  get options() { return this.children; }
  get value() { return this.isSelect ? (this.children[this.selectedIndex]?.value || '') : this._value; }
  set value(value) { if(this.isSelect) this.selectedIndex=this.children.findIndex(x=>x.value===value); else this._value=value; }
  append(...items) { this.children.push(...items); if(this.isSelect && this.selectedIndex<0 && this.children.length) this.selectedIndex=0; }
  replaceChildren(...items) { this.children=[]; this.selectedIndex=-1; this.append(...items); }
  addEventListener(name, fn) { this.handlers[name]=fn; }
  setAttribute() {} removeAttribute() {} focus() {}
  showModal() { this.open=true; } close() { this.open=false; }
}
const elements = new Map();
const element = id => { if(!elements.has(id)) elements.set(id,new Element()); return elements.get(id); };
element('patient').isSelect=true;
const ids=Array.from({length:105},(_,i)=>`DB-${i+1}`);
const context=vm.createContext({document:{getElementById:element,querySelectorAll:()=>[],createElement:()=>new Element()},AbortController,setTimeout,clearTimeout,console,
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
  assert.equal(element('clinic-load').hidden,true); assert.equal(element('patient').value,'DB-1');
  assert.equal(element('patients-previous').disabled,true);
  await element('patients-next').handlers.click(); assert.equal(element('patient').value,'DB-2');
  await element('patients-previous').handlers.click(); assert.equal(element('patient').value,'DB-1');
  element('patient').selectedIndex=49; await element('patient').handlers.change();
  await element('patients-next').handlers.click(); assert.equal(element('patient').value,'DB-51');
  await element('patients-previous').handlers.click(); assert.equal(element('patient').value,'DB-50');
  await element('patient-info').handlers.click(); assert.equal(element('patient-dialog').open,true);
  assert.equal(element('patient-info-fields').children[1].textContent,'Fictional popup name');
  await element('patients-next').handlers.click(); assert.equal(element('patient-dialog').open,false);
  assert.equal(element('patient-info-fields').children.length,0);
  for(let i=0;i<54;i++) await element('patients-next').handlers.click();
  assert.equal(element('patient').value,'DB-105'); assert.equal(element('patients-next').disabled,true);
  console.log('Passed: assigned clinic, sequential navigation, both page boundaries, last patient, popup and stale-detail clearing.');
})().catch(error=>{console.error(error);process.exitCode=1;});
