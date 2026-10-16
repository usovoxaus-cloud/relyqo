/* Execute the shipped phone controller; provider requests are simulated. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {parseHTML} = require('linkedom');
const html = fs.readFileSync('app/static/phone-recovery.html','utf8');
const script = fs.readFileSync('app/static/phone-recovery.js','utf8');

async function page({bind=false, language='ru', enabled=true, authenticated=true}={}) {
  const {document} = parseHTML(html);
  document.documentElement.lang = language;
  const requests=[], timers=[], events={};
  const fields = id => document.getElementById(id);
  Object.defineProperty(fields('region'),'value',{writable:true,value:''});
  for (const id of ['phoneForm','codeForm']) fields(id).reset=()=>{
    for(const input of fields(id).querySelectorAll('input'))input.value='';
  };
  for(const field of document.querySelectorAll('input'))field.focus=()=>{};
  const handlers={};
  for(const id of ['phoneForm','codeForm','restart'])fields(id).addEventListener=(event,fn)=>{handlers[id]=fn;};
  const context={document,location:{pathname:bind?'/account-phone':'/phone-recovery'},Intl,Date,
    setInterval:fn=>{timers.push(fn);return 1;},clearInterval:()=>{},
    window:{addEventListener:(name,fn)=>{events[name]=fn;}},
    fetch:async (url,options)=>{
      const body=options.body?JSON.parse(options.body):null; requests.push({url,body});
      if(url.endsWith('phone-options'))return{ok:true,json:async()=>({enabled,regions:[{code:'UZ',dial_code:'+998'},{code:'GB',dial_code:'+44'}]})};
      if(url.endsWith('recovery-phone')&&!body)return{ok:authenticated,status:401,json:async()=>({verified:false})};
      if(url.endsWith('recovery-phone')||url.endsWith('forgot-password-phone'))return{ok:true,json:async()=>({challenge:'a'.repeat(43),retry_after:60})};
      return{ok:true,json:async()=>({})};
    }};
  vm.runInNewContext(script,context);
  await new Promise(resolve=>setImmediate(resolve));
  const submit=async id=>handlers[id]({preventDefault(){}});
  return{fields,requests,submit,events};
}

test('unconfigured SMS and anonymous binding keep forms hidden',async()=>{
  for(const options of [{enabled:false},{bind:true,authenticated:false}]){
    const {fields}=await page(options);
    assert.equal(fields('phoneForm').hidden,true);
    assert.match(fields('status').textContent+fields('error').textContent,/недоступны|войдите/);
  }
});
test('international recovery passes country, keeps challenge in memory and resets secrets',async()=>{
  const {fields,requests,submit,events}=await page();
  fields('region').value='GB'; fields('phone').value='07700 900123';
  await submit('phoneForm');
  assert.deepEqual(requests.at(-1).body,{region:'GB',phone:'07700 900123'});
  fields('code').value='123456'; fields('newPassword').value=fields('confirmPassword').value='new-password-123';
  await submit('codeForm');
  assert.deepEqual(requests.at(-1).body,{challenge:'a'.repeat(43),code:'123456',new_password:'new-password-123',confirm_password:'new-password-123'});
  assert.equal(fields('codeForm').hidden,true);
  assert.equal(fields('newPassword').value,'');
  events.pagehide(); assert.equal(fields('phone').value,'');
});
test('binding requires current password, uses separate confirmation and Uzbek copy',async()=>{
  const {fields,requests,submit}=await page({bind:true,language:'uz'});
  assert.match(fields('title').textContent,/Tiklash/);
  assert.equal(fields('currentPassword').required,true);
  assert.equal(fields('newPassword').disabled,true);
  fields('region').value='UZ'; fields('phone').value='+998901234567'; fields('currentPassword').value='current-password';
  await submit('phoneForm'); assert.equal(fields('currentPassword').value,'');
  fields('code').value='123456'; await submit('codeForm');
  assert.equal(requests.at(-1).url,'/v1/auth/verify-phone');
  assert.deepEqual(Object.keys(requests.at(-1).body),['challenge','code']);
  assert.match(fields('message').textContent,/Telefon tasdiqlandi/);
});
test('mismatched passwords do not consume a code and restart cannot bypass cooldown',async()=>{
  const {fields,requests,submit}=await page();
  fields('region').value='UZ'; fields('phone').value='+998901234567'; await submit('phoneForm');
  const before=requests.length;
  fields('newPassword').value='long-password'; fields('confirmPassword').value='other-password';
  await submit('codeForm'); assert.equal(requests.length,before);
  assert.match(fields('error').textContent,/не совпадают/);
  await submit('restart'); assert.equal(fields('send').disabled,true);
  await submit('phoneForm'); assert.equal(requests.length,before);
});
