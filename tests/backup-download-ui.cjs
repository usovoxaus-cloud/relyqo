const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {parseHTML} = require('linkedom');
const settle = async () => {for (let i=0;i<8;i++) await new Promise(r=>setImmediate(r));};
const deferred = () => {let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};

function setup({picker, responseStatus=200}={}) {
  const {window,document}=parseHTML(fs.readFileSync('app/static/admin-control.html','utf8'));
  const form=document.getElementById('backupForm'),button=form.querySelector('button');
  const fields=Object.fromEntries([...form.querySelectorAll('input')].map(n=>[n.name,n]));
  Object.defineProperty(form,'elements',{value:fields});
  form.reset=()=>{for(const field of Object.values(fields))field.value='';};
  fields.current_password.value='test-admin-password';
  fields.passphrase.value=fields.confirm_passphrase.value='test-backup-password';
  const calls=[],downloads=[];const blob=new Blob(['RELYQO-BACKUP-1\nfixture']);
  window.showSaveFilePicker=picker?options=>{calls.push('picker');return picker(options);}:undefined;
  window.HTMLElement.prototype.click=function(){downloads.push({name:this.download,href:this.href});};
  class FormData {constructor(form){this.fields=form.elements;}*[Symbol.iterator](){for(const [name,field]of Object.entries(this.fields))yield [name,field.value];}}
  vm.runInNewContext(fs.readFileSync('app/static/backup-download.js','utf8'),{
    window,document,Date,FormData,setTimeout:()=>0,
    URL:{createObjectURL:()=> 'blob:backup-fixture',revokeObjectURL(){}},
    fetch:async()=>{calls.push('fetch');return {ok:responseStatus===200,status:responseStatus,json:async()=>({detail:'Доступ запрещён'}),blob:async()=>blob};}
  });
  function submit(){const event=new window.Event('submit',{cancelable:true});event.submitter=button;form.dispatchEvent(event);}
  return {submit,button,fields,calls,downloads,blob,document,status:document.getElementById('backupStatus')};
}

test('picker opens before export; saved status waits for the complete file close',async()=>{
  const closing=deferred(),writes=[];const x=setup({picker:async options=>{
    assert.match(options.suggestedName,/\.rqbackup$/);return {createWritable:async()=>({write:async value=>writes.push(value),close:()=>closing.promise,abort:async()=>{}})};
  }});
  x.submit();await settle();assert.deepEqual(x.calls,['picker','fetch']);assert.equal(writes[0],x.blob);
  assert.equal(x.button.disabled,true);assert.doesNotMatch(x.status.textContent,/Копия сохранена/);
  x.submit();await settle();assert.equal(x.calls.filter(x=>x==='fetch').length,1);
  closing.resolve();await settle();assert.match(x.status.textContent,/Копия сохранена в выбранную папку/);
  assert.equal(x.button.disabled,false);assert.equal(x.downloads.length,0);
  assert(Object.values(x.fields).every(f=>f.value===''));
});

test('cancelling the picker exports nothing and clears passwords',async()=>{
  const x=setup({picker:async()=>{const e=new Error('cancel');e.name='AbortError';throw e;}});
  x.submit();await settle();assert.deepEqual(x.calls,['picker']);assert.match(x.status.textContent,/Сохранение отменено/);
  assert.equal(x.button.disabled,false);assert(Object.values(x.fields).every(f=>f.value===''));
});

test('disk close failure aborts the write and never reports a saved copy',async()=>{
  let aborted=false;const x=setup({picker:async()=>({createWritable:async()=>({write:async()=>{},close:async()=>{throw Error('Disk full');},abort:async()=>{aborted=true;}})})});
  x.submit();await settle();assert.equal(aborted,true);assert.match(x.status.textContent,/Копия не сохранена/);
  assert.doesNotMatch(x.status.textContent,/Копия сохранена/);assert.equal(x.button.disabled,false);
});

test('browsers without the picker download a named file and explain where to find it',async()=>{
  const x=setup();x.submit();await settle();assert.deepEqual(x.calls,['fetch']);assert.equal(x.downloads.length,1);
  assert.match(x.downloads[0].name,/^relyqo-.*\.rqbackup$/);assert.match(x.status.textContent,/Ctrl \+ J/);
  assert.doesNotMatch(x.status.textContent,/Копия сохранена/);
});

test('expired login locks the admin interface and never writes a file',async()=>{
  let wrote=false;const x=setup({responseStatus:401,picker:async()=>({createWritable:async()=>{wrote=true;}})});
  x.submit();await settle();assert.equal(wrote,false);assert.equal(x.document.getElementById('controlContent').hidden,true);
  assert.equal(x.document.getElementById('controlLocked').hidden,false);assert.match(x.status.textContent,/не сохранена/);
});

test('different passwords stop before the picker and export request',async()=>{
  const x=setup({picker:async()=>{throw Error('Unexpected dialog');}});x.fields.confirm_passphrase.value='different';
  x.submit();await settle();assert.deepEqual(x.calls,[]);assert.match(x.status.textContent,/не совпадают/);
});
