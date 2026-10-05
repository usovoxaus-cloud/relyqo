const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');const {parseHTML}=require('linkedom');
const html=fs.readFileSync('app/static/me.html','utf8');
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
const response=(body,status=200)=>({ok:status<400,status,json:async()=>body});
async function account({returnTo='',loggedIn=false,pending=false,fail=false}={}){
  const {document,window}=parseHTML(html),calls=[];let signedIn=loggedIn,release;
  const location={search:returnTo?'?return_to='+encodeURIComponent(returnTo):'',href:'/me',reload(){}};
  const fetch=async(url,options={})=>{
    calls.push({url,options});
    if(url==='/v1/consumer/dashboard')return signedIn?response({username:'Fixture',favorites:[],ratings:[],photos:[]}):response({detail:'Войдите в аккаунт'},401);
    if(url==='/v1/auth/login'||url==='/v1/consumer/register'){
      if(pending)await new Promise(r=>release=r);
      if(fail)return response({detail:'Неверный логин или пароль'},401);
      signedIn=true;return response({role:'CONSUMER'});
    }
    throw Error('Unexpected request '+url);
  };
  class FormDataFixture extends Map{constructor(form){super([...form.querySelectorAll('[name]')].map(e=>[e.name||e.getAttribute('name'),e.value]));}}
  const context={document,window,location,fetch,URLSearchParams,FormData:FormDataFixture,localStorage:{getItem:()=>null},navigator:{},setTimeout,clearTimeout,Error};
  vm.runInNewContext([...document.querySelectorAll('script:not([src])')].map(s=>s.textContent).join('\n'),context);await settle();
  return {document,window,calls,location,release:()=>release?.(),submit:id=>document.getElementById(id).dispatchEvent(new window.Event('submit',{cancelable:true}))};
}
test('login return paths stay within supported site pages and do not loop to the login page',async()=>{
  for(const path of ['https://example.test','//example.test','/\\example.test','/\texample.test','/me','/me?return_to=/me','/me/','/consumer/../me','/%2f%2fexample.test','/unknown']){
    const x=await account({returnTo:path,loggedIn:true});assert.equal(x.location.href,'/me',path);
  }
  for(const path of ['/me/requests?id=own-request','/business/requests','/representative?object_key=manual%3Aone','/place?object_key=relyqo%3Aone','/community-rate?object_key=manual%3Aone']){
    const x=await account({returnTo:path,loggedIn:true});assert.equal(x.location.href,path);
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
  const x=await account({returnTo:'/me/requests?id=existing-conversation'});x.submit('loginForm');await settle();assert.equal(x.location.href,'/me/requests?id=existing-conversation');
});
