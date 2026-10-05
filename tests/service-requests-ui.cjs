const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const html=fs.readFileSync('app/static/service-requests.html','utf8');
const script=fs.readFileSync('app/static/service-requests.js','utf8');
const dictionary=JSON.parse(fs.readFileSync('app/static/i18n-uz.json','utf8'));
const settle=async()=>{for(let i=0;i<10;i++)await new Promise(resolve=>setImmediate(resolve));};
const base={id:'request-one',version:1,status:'ANSWERED',organization:{name:'Fixture organization',address:'Fixture address'},created_at:'2026-10-05T00:00:00Z',updated_at:'2026-10-05T00:00:00Z',messages:[{side:'BUSINESS',body:'An answer',created_at:'2026-10-05T00:00:00Z'}]};
async function setup({mode='consumer',status='ANSWERED',query='?id=request-one',lang='ru',fail=false,pending=false,auth=false,network=false,message='An answer'}={}){
  const {window,document}=parseHTML(html),calls=[],saved=[];
  document.documentElement.lang=lang;
  window.HTMLElement.prototype.scrollIntoView=function(){};
  window.confirm=()=>true;
  window.relyqoT=x=>lang==='uz'?(dictionary[x]||x):x;
  window.relyqoLanguageReady=Promise.resolve();
  let item=structuredClone({...base,status});
  item.messages[0].body=message;
  const location={pathname:mode==='consumer'?'/me/requests':mode==='business'?'/business/requests':'/admin/requests',search:query};
  const role=mode==='consumer'?'CONSUMER':mode==='business'?'BUSINESS_OWNER':'RELYQO_ADMIN';
  let resolvePost;
  async function fetch(url,options){
    const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
    const reply=(data,status=200)=>({ok:status<400,status,json:async()=>data});
    if(auth)return reply({detail:'Войдите в аккаунт'},401);
    if(body){
      if(network)throw new TypeError('Failed to fetch');
      if(pending)await new Promise(resolve=>resolvePost=resolve);
      if(fail)return reply({detail:'Обращение обновилось. Обновите переписку и повторите действие'},409);
      saved.push(body);
      item={...item,version:item.version+1,status:body.action==='resolve'?'RESOLVED':body.action==='withdraw'?'WITHDRAWN':body.action==='reopen'?'IN_PROGRESS':body.action==='reply'?'ANSWERED':'OPEN'};
      return reply(item);
    }
    if(url.includes('/context?'))return reply({organization:item.organization,ready:false,existing_id:null});
    if(url.includes('?offset='))return reply({role,items:query.includes('rating_id')?[]:[item],has_more:false});
    return reply(item);
  }
  vm.runInNewContext(script,{document,window,location,URLSearchParams,fetch,Date,Promise,Error,AbortController,setTimeout,clearTimeout});await settle();
  const get=id=>document.getElementById(id);
  const submit=id=>get(id).dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true}));
  const button=text=>[...get('requestActions').querySelectorAll('button')].find(b=>b.textContent===text);
  return{window,document,get,calls,saved,submit,button,release:()=>resolvePost?.(),item:()=>item};
}

test('new conversation needs unchecked explicit consent and never copies original rating text',async()=>{
  const x=await setup({query:'?rating_id=own-rating'});
  assert(!x.get('newRequest').hidden);assert(!x.get('shareConsent').checked);assert.equal(x.get('requestText').value,'');
  assert.match(x.get('deliveryNote').textContent,/ещё не подключён/);
  x.get('requestText').value='Please correct the situation';x.submit('createRequestForm');await settle();assert.equal(x.saved.length,0);
  x.get('shareConsent').checked=true;x.submit('createRequestForm');await settle();
  assert.deepEqual(x.saved[0],{rating_id:'own-rating',message:'Please correct the situation',consent:true});
  assert(x.get('newRequest').hidden);assert(!x.get('conversation').hidden);assert.equal(x.get('requestText').value,'');
});

test('only the consumer sees resolution; owners can take open requests into work',async()=>{
  const consumer=await setup();assert(consumer.button('Проблема решена'));
  consumer.button('Проблема решена').click();await settle();assert.equal(consumer.saved[0].action,'resolve');assert.equal(consumer.get('sendReply').textContent,'Продолжить обсуждение');
  consumer.get('replyText').value='Still need help';consumer.submit('replyForm');await settle();assert.equal(consumer.saved[1].action,'reopen');
  const owner=await setup({mode:'business',status:'OPEN'});assert(owner.button('Взять в работу'));assert(!owner.button('Проблема решена'));assert(!owner.button('Отозвать обращение'));
  const admin=await setup({mode:'admin',status:'WAITING_ORGANIZATION'});assert(admin.get('replyForm').hidden);assert(!admin.get('assignment').hidden);
});

test('stale update preserves draft and refresh keeps it available',async()=>{
  const x=await setup({fail:true});x.get('replyText').value='An unsent message';x.submit('replyForm');await settle();
  assert.equal(x.get('replyText').value,'An unsent message');assert(!x.get('requestError').hidden);
  x.get('reloadConversation').click();await settle();assert.equal(x.get('replyText').value,'An unsent message');
});

test('pending send prevents duplicate submissions and clears draft only on success',async()=>{
  const x=await setup({pending:true});x.get('replyText').value='A single message';x.submit('replyForm');x.submit('replyForm');await settle();
  assert.equal(x.calls.filter(c=>c.body).length,1);assert(x.get('sendReply').disabled);assert.equal(x.get('replyText').value,'A single message');
  assert(x.get('replyText').disabled);
  x.release();await settle();assert.equal(x.get('replyText').value,'');assert(!x.get('sendReply').disabled);
});

test('withdrawn conversation has no sharing actions and expired session shows login',async()=>{
  const x=await setup({status:'WITHDRAWN'});assert(x.get('replyForm').hidden);assert.equal(x.get('requestActions').children.length,0);
  const auth=await setup({auth:true,query:'?rating_id=own-rating'});assert(!auth.get('loginGate').hidden);assert.match(auth.get('loginLink').href,/return_to=/);assert(auth.get('newRequest').hidden);
});

test('Uzbek runtime labels and untrusted authored content remain separate',async()=>{
  const message='<img src=x onerror=alert(1)> Название организации';
  const x=await setup({lang:'uz',message});assert.equal(x.get('conversationStatus').textContent,dictionary['Организация ответила']);assert(x.button(dictionary['Проблема решена']));
  // A message is always inserted as text and protected from the global translator.
  assert.equal(x.get('messages').querySelector('p').getAttribute('data-user-content'),'');
  assert.equal(x.get('messages').querySelector('p').textContent,message);
  assert.equal(x.get('messages').querySelector('img'),null);
});

test('network failure keeps the draft, unlocks the form and shows a translated retry message',async()=>{
  const x=await setup({network:true,lang:'uz'});x.get('replyText').value='Preserve this text';x.submit('replyForm');await settle();
  assert.equal(x.get('replyText').value,'Preserve this text');assert(!x.get('replyText').disabled);
  assert.match(x.get('requestError').textContent,/Server bilan/);assert.equal(x.saved.length,0);
});

test('entry points connect profile, rating history, successful rating, business and admin',()=>{
  for(const file of ['me.html','rating-detail.html','community-rate.html','app.js'])assert.match(fs.readFileSync('app/static/'+file,'utf8'),/\/me\/requests/);
  for(const file of ['business-owner.html','owner.html'])assert.match(fs.readFileSync('app/static/'+file,'utf8'),/\/business\/requests/);
  assert.match(fs.readFileSync('app/static/admin-control.html','utf8'),/\/admin\/requests/);
});
