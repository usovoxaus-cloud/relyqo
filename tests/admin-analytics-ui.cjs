/* DOM integration tests. Install linkedom in an isolated development prefix. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {parseHTML}=require('linkedom');
const settle=async()=>{for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));};
const category={code:'CUSTOM_VET',label:'Ветеринарные клиники',group:'HEALTH',custom:true};

function dom(html){
  const {window,document}=parseHTML(html);
  // linkedom omits the browser's HTMLSelectElement.value setter.
  Object.defineProperty(window.HTMLSelectElement.prototype,'value',{
    configurable:true,
    get(){return [...this.options].find(o=>o.selected)?.value??this.options[0]?.value??'';},
    set(value){for(const o of this.options)o.selected=o.value===String(value);}
  });
  return {window,document};
}
function metrics(overrides={}){
  return {submitted:5,included:4,excluded:1,respondents:2,anonymous:1,satisfied:2,neutral:1,dissatisfied:1,
    satisfied_percent:50,verified_visits:6,dimensions:{overall:7,quality:6,service:8,cleanliness:7,value:7},...overrides};
}
function data(query){
  const p=new URLSearchParams(query);
  return {period:{start:p.get('start'),end:p.get('end'),timezone:'UTC'},filters:{source:'verified'},summary:metrics(),
    organizations:[{key:'org:one',name:'<img src=x onerror=alert(1)>',category:'CUSTOM_VET',category_label:category.label,...metrics()}],
    categories:[{code:'CUSTOM_VET',label:category.label,...metrics()}],
    trend:[{date:'2026-09-16',...metrics()}],methodology:{basis:'Test basis',respondents:'Unique accounts',visits:'Tracked visits',sources:'Separate sources'},ai:{configured:true}};
}
async function analyticsPage(unauthorized=false){
  const {window,document}=dom(fs.readFileSync('app/static/admin-analytics.html','utf8'));
  const requests=[];
  const context={document,window,URLSearchParams,Date,console,fetch:async(url,options={})=>{
    requests.push({url,options});let status=200,body;
    if(url==='/v1/public/service-categories')body={items:[category],groups:{HEALTH:'Здоровье',OTHER:'Другие услуги'}};
    else if(unauthorized){status=401;body={detail:'Войдите в аккаунт'};}
    else if(url.startsWith('/v1/admin/analytics/insights'))body={analysis:'<script>not executable</script>',generated_at:'2026-09-16T00:00:00Z',cached:false};
    else if(url.startsWith('/v1/admin/analytics?'))body=data(url.split('?')[1]);
    else if(url==='/v1/admin/service-categories')body=category;
    else throw Error('Unexpected URL '+url);
    return {ok:status===200,status,json:async()=>body};
  }};
  vm.runInNewContext(fs.readFileSync('app/static/admin-analytics.js','utf8'),context);
  await settle();return {window,document,requests};
}

test('private analytics renders exact values and treats all names and AI text as text',async()=>{
  const {document}=await analyticsPage();
  assert.equal(document.getElementById('content').hidden,false);
  assert.equal(document.getElementById('respondents').textContent,'2');
  assert.equal(document.getElementById('satisfaction').textContent,'50%');
  assert.equal(document.querySelectorAll('#organizations tr').length,1);
  assert.equal(document.querySelectorAll('#organizations img').length,0);
  assert.match(document.getElementById('aiText').textContent,/<script>/);
  assert.equal(document.querySelectorAll('#aiText script').length,0);
  assert.equal(document.querySelectorAll('#trend polyline').length,2);
});

test('changing unapplied filters cannot attach an AI analysis to the wrong visible report',async()=>{
  const {window,document,requests}=await analyticsPage();
  const reportRequest=requests.find(r=>r.url.startsWith('/v1/admin/analytics?'));
  document.getElementById('start').value='2020-01-01';
  document.getElementById('analyze').dispatchEvent(new window.Event('click'));
  await settle();
  const ai=requests.filter(r=>r.url.startsWith('/v1/admin/analytics/insights')).at(-1);
  assert.equal(ai.url.split('?')[1],reportRequest.url.split('?')[1]);
});

test('unauthenticated visitors see only the login prompt and never request AI insights',async()=>{
  const {document,requests}=await analyticsPage(true);
  assert.equal(document.getElementById('content').hidden,true);
  assert.equal(document.getElementById('locked').hidden,false);
  assert.equal(document.querySelectorAll('#organizations tr').length,0);
  assert.equal(requests.some(r=>r.url.includes('/insights')),false);
});

test('administrator category form submits a name and group and displays confirmation',async()=>{
  const {window,document,requests}=await analyticsPage();
  document.getElementById('categoryName').value='Ветеринарные клиники';
  document.getElementById('categoryGroup').value='HEALTH';
  document.getElementById('categoryForm').dispatchEvent(new window.Event('submit',{cancelable:true}));
  await settle();
  const sent=requests.find(r=>r.url==='/v1/admin/service-categories');
  assert.deepEqual(JSON.parse(sent.options.body),{label:'Ветеринарные клиники',group:'HEALTH'});
  assert.match(document.getElementById('categoryStatus').textContent,/добавлена/);
});

test('new categories populate static and subsequently created forms without duplicates',async()=>{
  const {window,document}=dom('<html><body><select id="serviceCategory"><option value="ALL">Все</option></select><select name="category"><option value="OTHER">Другие</option></select></body></html>');
  vm.runInNewContext(fs.readFileSync('app/static/service-categories.js','utf8'),{
    window,document,MutationObserver:window.MutationObserver,AbortController,setTimeout,clearTimeout,
    fetch:async()=>({ok:true,json:async()=>({items:[category]})})
  });
  document.dispatchEvent(new window.Event('DOMContentLoaded'));
  await window.relyqoCategoriesReady;await settle();
  for(const select of document.querySelectorAll('select'))assert.equal(select.querySelectorAll('option[value="CUSTOM_VET"]').length,1);
  const newSelect=document.createElement('select');newSelect.name='category';document.body.append(newSelect);await settle();
  assert.equal(newSelect.options.length,1);
  assert.equal(window.relyqoCategoryLabel('CUSTOM_VET'),category.label);
  assert.equal(window.relyqoCategoryGroup('CUSTOM_VET'),'HEALTH');
});
