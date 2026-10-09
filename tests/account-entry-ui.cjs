const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');const {parseHTML}=require('linkedom');
const html=fs.readFileSync('app/static/welcome.html','utf8');
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
const response=(body,status=200)=>({ok:status<400,status,json:async()=>body});
async function account({returnTo='',loggedIn=false,pending=false,fail=false,timeout=false,recovery=false}={}){
  const {document,window}=parseHTML(html),calls=[],timers=new Set();let signedIn=loggedIn,release;
  const location={search:returnTo?'?return_to='+encodeURIComponent(returnTo):'',href:'/welcome',origin:'https://relyqo.onrender.com',replace(value){this.href=value},reload(){}};
  const fetch=async(url,options={})=>{
    calls.push({url,options});
    if(url==='/v1/consumer/dashboard')return signedIn?response({username:'Fixture',favorites:[],ratings:[],photos:[]}):response({detail:'Войдите в аккаунт'},401);
    if(url==='/v1/auth/login'||url==='/v1/consumer/register'){
      if(timeout)await new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'}))));
      if(pending)await new Promise(r=>release=r);
      if(fail)return response({detail:'Неверный логин или пароль'},401);
      signedIn=true;return response({role:'CONSUMER',...(recovery?{recovery_code:'fixture-recovery-code'}:{})});
    }
    throw Error('Unexpected request '+url);
  };
  class FormDataFixture extends Map{constructor(form){super([...form.querySelectorAll('[name]')].map(e=>[e.name||e.getAttribute('name'),e.value]));}}
  const context={document,window,location,fetch,URL,URLSearchParams,FormData:FormDataFixture,localStorage:{getItem:()=>null},navigator:{},AbortController,setTimeout:fn=>(timers.add(fn),fn),clearTimeout:fn=>timers.delete(fn),Error};
  vm.runInNewContext(fs.readFileSync('app/static/welcome.js','utf8'),context);await settle();
  return {document,window,calls,location,release:()=>release?.(),expire:()=>[...timers].forEach(fn=>fn()),submit:id=>document.getElementById(id).dispatchEvent(new window.Event('submit',{cancelable:true}))};
}
test('entry return paths reject external hosts, normalization and login loops',async()=>{
  for(const path of ['https://example.test','//example.test','/\\example.test','/\texample.test','/welcome','/me/','/consumer/../me','/%2f%2fexample.test','/unknown']){
    const x=await account({returnTo:path});x.submit('loginForm');await settle();assert.equal(x.location.href,'/consumer?lang=ru',path);
  }
  for(const path of ['/notifications','/me','/me/requests?id=own-request','/place?object_key=relyqo%3Aone','/community-rate?object_key=manual%3Aone','/rate?token=old-link']){
    const x=await account({returnTo:path});x.submit('loginForm');await settle();assert.equal(x.location.href,path+(path.includes('?')?'&':'?')+'lang=ru');
  }
});
test('pending authentication sends once across both forms and preserves input on failure',async()=>{
  const x=await account({pending:true,fail:true});const username=x.document.querySelector('#loginForm [name=username]'),password=x.document.querySelector('#loginForm [name=password]');
  username.value='fixture-user';password.value='fixture-password';
  x.submit('loginForm');x.submit('loginForm');x.submit('registerForm');await settle();
  assert.equal(x.calls.filter(c=>c.options.method==='POST').length,1);assert(password.disabled);
  x.release();await settle();assert(!password.disabled);assert.equal(username.value,'fixture-user');assert.equal(password.value,'fixture-password');
  assert(x.document.getElementById('authError').textContent.includes('Неверный'));
  x.submit('loginForm');await settle();assert.equal(x.calls.filter(c=>c.options.method==='POST').length,2);x.release();await settle();
});
test('successful sign-in returns to the requested conversation without losing its identifier',async()=>{
  const x=await account({returnTo:'/me/requests?id=existing-conversation'});x.submit('loginForm');await settle();assert.equal(x.location.href,'/me/requests?id=existing-conversation&lang=ru');
});
test('a timed out login unlocks controls and keeps the form available for a deliberate retry',async()=>{
  const x=await account({timeout:true}),input=x.document.querySelector('#loginForm [name=username]');input.value='fixture';x.submit('loginForm');await settle();assert(input.disabled);
  x.expire();await settle();assert(!input.disabled);assert.equal(input.value,'fixture');assert.match(x.document.getElementById('authError').textContent,/Проверьте соединение/);
});

test('first launch shows registration separately and login toggles without submitting',async()=>{
  const x=await account();assert.equal(x.document.getElementById('registerForm').hidden,false);assert.equal(x.document.getElementById('loginForm').hidden,true);
  x.document.getElementById('showLogin').click();assert.equal(x.document.getElementById('registerForm').hidden,true);assert.equal(x.document.getElementById('loginForm').hidden,false);assert.equal(x.calls.length,0);
});
test('registration waits for recovery-code acknowledgement before opening the app',async()=>{
  const x=await account({recovery:true});x.document.documentElement.lang='uz';x.submit('registerForm');await settle();
  assert.equal(x.location.href,'/welcome');assert.equal(x.document.getElementById('newRecoveryNotice').hidden,false);assert.equal(x.document.getElementById('auth').hidden,true);
  assert.equal(JSON.parse(x.calls[0].options.body).language,'uz');assert.equal(x.document.getElementById('newRecoveryCode').textContent,'fixture-recovery-code');
  x.document.getElementById('continueAfterRecovery').click();await settle();assert.equal(x.location.href,'/consumer?lang=uz');assert.equal(x.document.getElementById('newRecoveryCode').textContent,'');
});
