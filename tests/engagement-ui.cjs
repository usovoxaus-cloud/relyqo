const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');const {parseHTML}=require('linkedom');
const read=name=>fs.readFileSync('app/static/'+name,'utf8');const dictionary=JSON.parse(read('i18n-uz.json'));
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
function dom(html,lang='ru'){
  const {document,window}=parseHTML(html);document.documentElement.lang=lang;window.relyqoLanguageReady=Promise.resolve();window.relyqoT=text=>lang==='uz'?(dictionary[text]||text):text;
  Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.hasAttribute('selected'))?.value||this.options[0]?.value||'';},set(v){for(const o of this.options)o.removeAttribute('selected');[...this.options].find(o=>o.value===v)?.setAttribute('selected','');}});
  return {document,window};
}
const reply=(data,status=200)=>({ok:status<400,status,json:async()=>data});

async function notifications(lang='ru'){
  const {document,window}=dom('<html><body><main></main></body></html>',lang);let calls=0,interval,status=200;
  let data={unread:1,overdue:1,pending_claims:0,items:[{name:'<img src=x onerror=alert(1)> Кафе',status:'ANSWERED',href:'/me/requests?id=one'}],business:false,admin:false};
  vm.runInNewContext(read('engagement.js'),{document,window,AbortController,setTimeout,clearTimeout,setInterval:fn=>(interval=fn,1),clearInterval:()=>{},fetch:async()=>{calls++;return reply(data,status);}});await settle();
  return {document,window,poll:()=>interval(),calls:()=>calls,setData:x=>data=x,setStatus:x=>status=x};
}
test('in-app inbox renders unread counts and safe links; polling updates without reload',async()=>{
  const x=await notifications();const box=x.document.getElementById('engagementInbox');assert(!box.hidden);assert.match(box.textContent,/Уведомления · 1/);assert.equal(box.querySelector('img'),null);
  assert(box.textContent.includes('<img src=x onerror=alert(1)> Кафе'));assert.equal(box.querySelector('a').getAttribute('href'),'/me/requests?id=one');
  x.setData({unread:0,overdue:0,pending_claims:0,items:[],business:false,admin:false});x.poll();await settle();assert(!box.textContent.includes('· 1'));assert.match(box.textContent,/Новых сообщений нет/);
});
test('hidden tabs do not poll; expired sessions clear private notification names',async()=>{
  const x=await notifications();const before=x.calls();Object.defineProperty(x.document,'hidden',{configurable:true,value:true});x.poll();await settle();assert.equal(x.calls(),before);
  Object.defineProperty(x.document,'hidden',{configurable:true,value:false});x.setStatus(401);x.poll();await settle();assert(x.document.getElementById('engagementInbox').hidden);assert.equal(x.document.querySelectorAll('.engagementLinks a').length,0);
});
test('Uzbek notification controls and claim decisions use translated labels',async()=>{
  const x=await notifications('uz');x.setData({unread:1,overdue:0,pending_claims:0,items:[{name:'Кафе',status:'CLAIM_APPROVED',href:'/representative?object_key=manual%3Aone'}],business:true,admin:false});x.poll();await settle();
  const text=x.document.getElementById('engagementInbox').textContent;assert(text.includes(dictionary['Есть решение по вашей заявке']));assert(text.includes('Кафе'));assert(text.includes(dictionary['Кабинет представителя']));
});

async function claims({admin=false,fail=false,existing=null,lang='ru'}={}){
  const {document,window}=dom(read('representative.html'),lang),posts=[];
  const row={id:'claim-one',version:1,status:'PENDING',organization:{name:'Fixture organization',address:'Fixture address'},contact:'office@example.test',evidence:'Independent official verification evidence',object_key:'manual:one',applicant:'fixture-user',applicant_active:true};
  const location={pathname:admin?'/admin/representatives':'/representative',search:admin?'':'?object_key=manual%3Aone'};
  const fetch=async(url,options)=>{
    if(options.body){const body=JSON.parse(options.body);if(url==='/v1/representation/read')return reply({read:true});posts.push({url,body});return fail?reply({detail:'Заявка обновилась. Обновите страницу'},409):reply({...row,status:body.action==='approve'?'APPROVED':'PENDING'});}
    if(url.includes('/context?'))return reply({organization:row.organization,claim:existing?{...row,...existing}:null,represented:false});
    return reply({admin,items:admin||existing?[{...row,...existing}]:[],has_more:false});
  };
  vm.runInNewContext(read('representative.js'),{document,window,location,URLSearchParams,fetch,AbortController,setTimeout,clearTimeout,Error});await settle();
  const get=id=>document.getElementById(id),submit=(form,button)=>{const e=new window.Event('submit',{bubbles:true,cancelable:true});if(button)Object.defineProperty(e,'submitter',{value:button});form.dispatchEvent(e);};
  return {document,window,posts,get,submit};
}
test('representative application requires separate consent and preserves text after a conflict',async()=>{
  const x=await claims({fail:true});assert(!x.get('claimNew').hidden);assert(!x.get('claimConsent').checked);x.get('claimContact').value='office@example.test';x.get('claimEvidence').value='Officially verifiable representative';
  x.submit(x.get('claimForm'));await settle();assert.equal(x.posts.length,0);
  x.get('claimConsent').checked=true;x.submit(x.get('claimForm'));await settle();assert.equal(x.posts[0].body.object_key,'manual:one');assert.equal(x.get('claimEvidence').value,'Officially verifiable representative');assert(!x.get('claimsError').hidden);
});
test('admin cannot approve before confirming independent verification; version is submitted',async()=>{
  const x=await claims({admin:true});const form=x.document.querySelector('.claimCard form'),button=form.querySelector('button[value=approve]');form.querySelector('textarea').value='Confirmed through the official telephone number';
  x.submit(form,button);await settle();assert.equal(x.posts.length,0);
  form.querySelector('input[type=checkbox]').checked=true;x.submit(form,button);await settle();assert.equal(x.posts[0].body.verified,true);assert.equal(x.posts[0].body.version,1);assert.equal(x.posts[0].body.action,'approve');
});
test('approved applicant sees the reply cabinet without an editable claim or account role change',async()=>{
  const x=await claims({existing:{status:'APPROVED'},lang:'uz'});assert(x.get('claimNew').hidden);assert.equal(x.document.querySelector('.claimCard a').getAttribute('href'),'/business/requests');assert(x.get('claimsNotice').textContent.includes(dictionary['Доступ подтверждён']));
});
