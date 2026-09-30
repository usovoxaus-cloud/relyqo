const {test}=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const {parseHTML}=require('linkedom');
const read=name=>fs.readFileSync('app/static/'+name,'utf8');
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
const reply=(data,status=200)=>({ok:status===200,status,json:async()=>data});

test('web search and the old mobile injection share one search screen and preserve location',async()=>{
  const {document,window}=parseHTML(read('nearby.html'));
  Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.hasAttribute('selected'))?.value||this.options[0]?.value||''},set(v){for(const o of this.options)o.removeAttribute('selected');[...this.options].find(o=>o.value===v)?.setAttribute('selected','');}});
  const context={document,window,Event:window.Event,MutationObserver:window.MutationObserver,AbortController,setTimeout,clearTimeout,localStorage:{getItem:()=>null,setItem(){}},fetch:async()=>reply({content:{ru:{title:'Найдите услугу',hint:'Выберите свой город'}}})};
  vm.runInNewContext(read('consumer-search.js'),context);await settle();
  assert.equal(document.querySelector('.consumerTitle').textContent,'Найдите услугу');
  assert.equal(document.querySelector('.consumerPlace').hasAttribute('open'),false);
  assert(document.querySelector('.consumerPlace #ratedRegion'));
  document.querySelector('[data-category="HEALTH"]').click();
  assert.equal(document.getElementById('ratedCategory').value,'HEALTH');
  const native=vm.runInNewContext(fs.readFileSync('mobile/src/consumer.ts','utf8').replace('export const CONSUMER_PRESENTATION =','globalThis.source =')+';source');
  vm.runInNewContext(native,context);assert.equal(document.querySelectorAll('.consumerTitle').length,1);
});

test('admin deep links and back navigation display the requested section after sign-in',async()=>{
  const {document,window}=parseHTML(read('admin.html'));window.scrollTo=()=>{};
  const location={pathname:'/admin',hash:'#applications'},requests=[];
  const context={document,window,location,URLSearchParams,Event:window.Event,Intl,fetch:async url=>{
    requests.push(url);
    if(url==='/v1/auth/me')return reply({role:'RELYQO_ADMIN',username:'admin-fixture'});
    if(url==='/v1/admin/dashboard')return reply({overview:{},recent_audit:[]});
    return reply({items:[],count:0});
  }};
  vm.runInNewContext([...document.querySelectorAll('script:not([src])')].map(s=>s.textContent).join('\n'),context);
  vm.runInNewContext(read('management-nav.js'),context);await settle();
  assert.equal(document.getElementById('appView').classList.contains('hidden'),false);
  assert.equal(document.querySelector('.sectionView.active').id,'section-applications');
  assert.equal(document.querySelector('[data-management-nav] [aria-current=page]').textContent,'Организации');
  location.hash='#ads';window.dispatchEvent(new window.Event('hashchange'));
  assert.equal(document.querySelector('.sectionView.active').id,'section-ads');
  assert.equal(document.querySelector('[data-management-nav] [aria-current=page]').textContent,'Реклама');
  location.hash='#dashboard';window.dispatchEvent(new window.Event('hashchange'));
  assert.equal(document.querySelector('.sectionView.active').id,'section-dashboard');
  location.hash='#untrusted';window.dispatchEvent(new window.Event('hashchange'));
  assert.equal(document.querySelector('.sectionView.active').id,'section-dashboard');
  assert(document.querySelector('[href="/admin/editor"]'));
  assert(document.querySelector('[href="/admin/settings"]'));
});

test('generic business analytics uses the signed-in tenant endpoint and escapes server labels',async()=>{
  const {document,window}=parseHTML(read('business.html')),requests=[];
  const data={organization:{name:'School <one>',branch:'Main',city:'Tashkent'},relyqo_score:80,rating_count:1,verified_visits:1,
    metrics:{food:80},metric_labels:{food:'<img src=x onerror=alert(1)>'},history:[],ai:{configured:false},
    pilot:{sample_target:20,remaining_to_target:19,sample_status:'EARLY',submitted_ratings:1,completion_rate:100,incomplete_visits:0,pending_review:0,strongest_category:{label:'Обучение',score:80},weakest_category:{label:'Условия',score:80}}};
  const context={document,window,fetch:async url=>{requests.push(url);return reply(data);}};
  vm.runInNewContext([...document.querySelectorAll('script:not([src])')].map(s=>s.textContent).join('\n'),context);await settle();
  assert(requests[0].startsWith('/v1/business-owner/dashboard?'));
  assert.equal(document.getElementById('name').textContent,'School <one>');
  assert.match(document.getElementById('metrics').textContent,/<img/);
  assert.equal(document.querySelector('#metrics img'),null);
  assert.equal(document.getElementById('runAI').disabled,true);
});

test('unauthenticated business dashboard shows a login and hides analytic placeholders',async()=>{
  const {document,window}=parseHTML(read('business.html'));
  vm.runInNewContext([...document.querySelectorAll('script:not([src])')].map(s=>s.textContent).join('\n'),{document,window,fetch:async()=>reply({detail:'Войдите в кабинет бизнеса'},401)});
  await settle();assert.equal(document.getElementById('businessLogin').classList.contains('hidden'),false);
  for(const node of document.querySelectorAll('.grid,.pilot,.aiCard'))assert(node.classList.contains('hidden'));
});

test('settings remain locked for consumer accounts',async()=>{
  const {document,window}=parseHTML(read('admin-settings.html'));
  vm.runInNewContext(read('admin-settings.js'),{document,window,fetch:async()=>reply({role:'CONSUMER'})});await settle();
  assert.equal(document.getElementById('settingsContent').hidden,true);
  assert.equal(document.getElementById('settingsLocked').hidden,false);
});

test('organization search rejects late responses and resets pagination when the query changes',async()=>{
  const {document,window}=parseHTML(read('admin.html')),requests=[];
  const context={document,window,URLSearchParams,fetch:url=>new Promise(resolve=>requests.push({url,resolve}))};
  vm.runInNewContext(read('admin-directory.js'),context);
  const submit=()=>document.getElementById('directoryForm').dispatchEvent(new window.Event('submit',{cancelable:true}));
  document.getElementById('directoryQuery').value='old';submit();
  document.getElementById('directoryQuery').value='new';submit();
  const result=name=>({items:[{id:'one',name,city:'Tashkent',category:'EDUCATION',rating_count:0,profile_status:'PUBLISHED',branches:[]}],total:51,next_offset:50});
  requests[1].resolve(reply(result('New school')));await settle();
  requests[0].resolve(reply(result('Old school')));await settle();
  assert.match(document.getElementById('organizationDirectory').textContent,/New school/);
  assert.doesNotMatch(document.getElementById('organizationDirectory').textContent,/Old school/);
  document.getElementById('directoryQuery').value='third';document.getElementById('directoryMore').click();
  const params=new URLSearchParams(requests[2].url.split('?')[1]);
  assert.equal(params.get('q'),'third');assert.equal(params.get('offset'),'0');
  requests[2].resolve(reply(result('Third school')));await settle();
  assert.doesNotMatch(document.getElementById('organizationDirectory').textContent,/New school/);
});

test('staff login accepts both existing and generic staff roles, but does not display an owner workspace',async()=>{
  for(const role of ['FREGAT_STAFF','BUSINESS_STAFF','BUSINESS_OWNER']) {
    const {document,window}=parseHTML(read('staff.html'));
    vm.runInNewContext([...document.querySelectorAll('script:not([src])')].map(s=>s.textContent).join('\n'),{document,window,fetch:async()=>reply({role,username:'cashier-fixture'})});await settle();
    assert.equal(document.getElementById('staffCard').classList.contains('hidden'),role==='BUSINESS_OWNER',role);
  }
});
