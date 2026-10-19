const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const html=fs.readFileSync('app/static/business-owner.html','utf8');
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
const reply=(data,status=200)=>({ok:status<400,status,json:async()=>data});

async function setup({signedIn=false,loginRequest,geolocation}={}){
  const {document,window}=parseHTML(html),calls=[],handlers={},timers=new Map();let timerId=0;
  Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
    get(){return [...this.options].find(option=>option.selected)?.value??this.options[0]?.value??'';},
    set(value){for(const option of this.options)option.selected=option.value===String(value);}});
  window.scrollTo=()=>{};
  window.relyqoCategoriesReady=Promise.resolve();window.relyqoLanguageReady=Promise.resolve();
  for(const form of document.querySelectorAll('form')){
    const original=form.addEventListener.bind(form);
    form.addEventListener=(event,handler)=>{if(event==='submit')handlers[form.id]=handler;else original(event,handler);};
    Object.defineProperty(form,'elements',{value:new Proxy({namedItem:name=>form.querySelector(`[name="${name}"]`)},{get:(target,name)=>target[name]||form.querySelector(`[name="${name}"]`)})});
    form.reset=()=>{};
  }
  class FormValues extends Map{
    constructor(form){super([...form.querySelectorAll('[name]')].filter(input=>!input.disabled).map(input=>[input.name||input.getAttribute('name'),input.value||'']));}
  }
  const profile={username:'pilot-owner',organization_name:'Pilot company',branch_id:'pilot-branch',category:'PROFESSIONAL_SERVICE',profile_status:'VERIFIED_PARTNER',city:'Tashkent',address:'Fixture street 1',latitude:null,longitude:null};
  const context={document,window,FormData:FormValues,URLSearchParams,AbortController,navigator:{geolocation},location:{reload(){}},
    setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id),
    fetch:async(url,options={})=>{
      calls.push({url,body:options.body?JSON.parse(options.body):null});
      if(url==='/v1/auth/login'){
        const result=loginRequest?await loginRequest(options):reply({role:'BUSINESS_OWNER'});
        if(result.ok)signedIn=true;
        return result;
      }
      if(url==='/v1/business-owner/profile')return signedIn?reply(profile):reply({detail:'Войдите в аккаунт'},401);
      return reply({detail:'Unexpected request'},500);
    }};
  vm.runInNewContext([...document.querySelectorAll('script:not([src])')].map(script=>script.textContent).join('\n'),context);
  await settle();
  const get=id=>document.getElementById(id);
  get('loginForm').querySelector('[name=username]').value='pilot-owner';
  get('loginForm').querySelector('[name=password]').value='fixture-only-password';
  return{document,window,calls,timers,get,submit:(id,submitter=null)=>handlers[id]({preventDefault(){},currentTarget:get(id),submitter})};
}

test('owner can sign in when a form submission has no submitter button',async()=>{
  const x=await setup();
  await assert.doesNotReject(x.submit('loginForm'));
  assert.equal(x.calls.filter(call=>call.url==='/v1/auth/login').length,1);
  assert(!x.get('dashboard').classList.contains('hidden'));
  assert.equal(x.get('organizationTitle').textContent,'Pilot company');
});

test('repeated submissions and switching auth forms cannot start concurrent account writes',async()=>{
  let finish;
  const x=await setup({loginRequest:()=>new Promise(resolve=>finish=resolve)});
  const first=x.submit('loginForm',x.get('loginForm').querySelector('[type=submit]'));
  const second=x.submit('loginForm',x.get('loginForm').querySelector('[type=submit]'));
  const registration=x.submit('registerForm',x.get('registerForm').querySelector('[type=submit]'));
  try{
    assert.equal(x.calls.filter(call=>call.body).length,1);
    assert.equal(x.calls.at(-1).body.username,'pilot-owner');
    assert.equal(x.get('loginForm').querySelector('[name=username]').disabled,true);
  }finally{
    finish(reply({detail:'Temporary failure'},503));
    await Promise.all([first,second,registration]);
  }
  assert.equal(x.get('loginForm').querySelector('[name=username]').disabled,false);
  assert.equal(x.get('loginForm').querySelector('[name=username]').value,'pilot-owner');
  assert.equal(x.get('loginForm').querySelector('[name=password]').value,'fixture-only-password');
});

test('a timed-out login unlocks its form and keeps the typed credentials for retry',async()=>{
  const x=await setup({loginRequest:options=>new Promise((resolve,reject)=>options.signal?.addEventListener('abort',()=>reject(Object.assign(new Error('Aborted'),{name:'AbortError'}))))});
  const pending=x.submit('loginForm',x.get('loginForm').querySelector('[type=submit]'));
  assert.equal(x.timers.size,1);
  [...x.timers.values()][0]();await pending;
  assert.equal(x.timers.size,0);
  assert.equal(x.get('loginForm').querySelector('[type=submit]').disabled,false);
  assert.equal(x.get('loginForm').querySelector('[name=username]').value,'pilot-owner');
  assert.match(x.get('authError').textContent,/долго|время/i);
});

test('denied GPS is reported inside the visible business profile without changing coordinates',async()=>{
  const x=await setup({signedIn:true,geolocation:{getCurrentPosition(resolve,reject){reject({code:1});}}});
  x.document.querySelector('[data-view=profile]').click();
  const latitude=x.get('profileForm').querySelector('[name=latitude]');latitude.value='41.25';
  x.document.querySelector('.locate[data-form=profileForm]').click();await settle();
  assert(x.get('authView').classList.contains('hidden'));
  assert(!x.get('profileMessage').classList.contains('hidden'));
  assert.match(x.get('profileMessage').textContent,/местоположен/);
  assert.equal(latitude.value,'41.25');
  assert.equal(x.calls.filter(call=>call.body).length,0);
});

test('profile and QR forms retain submitted values when their controls are locked',async()=>{
  const x=await setup({signedIn:true});
  x.get('profileForm').querySelector('[name=organization_name]').value='Edited fixture';
  x.get('profileForm').querySelector('[name=latitude]').value='41.25';
  x.get('profileForm').querySelector('[name=longitude]').value='69.25';
  x.get('profileForm').querySelector('[name=country_code]').value='uz';
  await x.submit('profileForm');
  const saved=x.calls.find(call=>call.url==='/v1/business-owner/profile'&&call.body);
  assert.equal(saved.body.organization_name,'Edited fixture');
  assert.equal(saved.body.latitude,41.25);assert.equal(saved.body.longitude,69.25);
  assert.equal(saved.body.country_code,'UZ');
  const reference=x.get('qrForm').querySelector('[name=transaction_reference]');reference.value=' ORDER-1 ';
  await x.submit('qrForm');
  assert.equal(x.calls.at(-1).body.transaction_reference,'ORDER-1');
  assert(!x.get('qrMessage').classList.contains('hidden'));
  assert.equal(reference.disabled,false);assert.equal(reference.value,' ORDER-1 ');
});

test('mobile owner navigation exposes the inbox directly from every dashboard view',async()=>{
  const x=await setup({signedIn:true});
  for(const view of ['overview','profile','qr']){
    x.document.querySelector(`[data-view=${view}]`).click();
    const inbox=x.document.querySelector('.mobileBar a[href="/business/requests"]');
    assert(inbox,'The inbox must remain accessible outside the overview');
    assert.match(inbox.textContent,/Обращения/);
    assert(!inbox.closest('.view'));
  }
});
