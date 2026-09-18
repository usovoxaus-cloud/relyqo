/* Run with node --test; linkedom is a development-only DOM harness. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {parseHTML}=require('linkedom');
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
function dom(html){const {window,document}=parseHTML(html);Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.selected)?.value??this.options[0]?.value??'';},set(value){for(const o of this.options)o.selected=o.value===String(value);}});return {window,document};}
const read=name=>fs.readFileSync('app/static/'+name,'utf8');
const dictionary=JSON.parse(read('i18n-uz.json'));

test('Uzbek translates labels, placeholders, late errors; leaves user content and values unchanged',async()=>{
 const {window,document}=dom('<html><head><title>Все отзывы</title></head><body><h1>Все отзывы</h1><p data-user-content>Все отзывы</p><input placeholder="Новый пароль" value="Все отзывы"><textarea placeholder="Новый пароль">Все отзывы</textarea></body></html>');let assigned;
 const context={window,document,navigator:{language:'ru'},location:{search:'?lang=uz',protocol:'https:',href:'https://example.test/me?lang=uz#token=private',assign:v=>assigned=v},localStorage:{getItem:()=>null,setItem(){}},URL,URLSearchParams,MutationObserver:window.MutationObserver,fetch:async()=>({ok:true,json:async()=>dictionary})};
 vm.runInNewContext(read('i18n.js'),context);document.dispatchEvent(new window.Event('DOMContentLoaded'));await settle();
 assert.equal(document.documentElement.lang,'uz');assert.equal(document.querySelector('h1').textContent,'Barcha sharhlar');assert.equal(document.querySelector('input').placeholder,dictionary['Новый пароль']);assert.equal(document.querySelector('textarea').placeholder,dictionary['Новый пароль']);assert.equal(document.querySelector('input').value,'Все отзывы');assert.equal(document.querySelector('textarea').value,'Все отзывы');assert.equal(document.querySelector('[data-user-content]').textContent,'Все отзывы');
 const error=document.createElement('p');error.textContent='Проверьте введённые данные.';document.body.append(error);await settle();assert.equal(error.textContent,dictionary['Проверьте введённые данные.']);
 const select=document.querySelector('.languageBar select');select.value='ru';select.dispatchEvent(new window.Event('change'));await settle();assert.equal(assigned,'/me?lang=ru#token=private');
});

test('feedback form keeps up to five distinct reasons and preserves comment text',async()=>{
 const {window,document}=dom('<html lang="uz"><body><div id="feedbackFields"></div></body></html>');
 const items=Array.from({length:6},(_,i)=>({code:'R'+i,label:'RU'+i,label_uz:'UZ'+i}));
 vm.runInNewContext(read('feedback-form.js'),{window,document,fetch:async()=>({ok:true,json:async()=>({items})})});await settle();
 const checks=document.querySelectorAll('input');for(const input of checks){input.checked=true;input.dispatchEvent(new window.Event('change'));}
 document.getElementById('feedbackComment').value='  <script>literal text</script>  ';
 assert.equal(window.relyqoFeedback().reasons.length,5);assert.equal(checks[5].checked,false);assert.equal(window.relyqoFeedback().comment,'<script>literal text</script>');assert.equal(document.querySelector('span').textContent,'UZ0');assert.equal(document.querySelectorAll('script').length,0);
});

async function control(denied=false){const {window,document}=dom(read('admin-control.html'));const requests=[];const item={id:'case1',kind:'SIGNAL',organization:'<img src=x onerror=alert(1)>',details:'Signal',status:'PENDING',rating:{overall:4,reasons:['LONG_WAIT'],comment:'<script>private</script>'},ai_analysis:'<img src=x>',photo_url:'/v1/admin/control/photos/test'};
 const fetch=async(url,options={})=>{requests.push({url,options});let body,status=200;if(url==='/v1/public/feedback-reasons')body={items:[{code:'LONG_WAIT',label:'Долго ждал',label_uz:'Uzoq kutdim'}]};else if(denied){status=403;body={detail:'Доступ запрещён'};}else if(url.includes('/control/cases?'))body={legacy:[],items:[item],next_offset:null};else if(url.includes('/control/feedback?'))body={items:[item],next_offset:null};else if(url.includes('/analytics/insights?'))body={analysis:'<script>Analysis</script>'};else throw Error('Unexpected '+url);return {ok:status===200,status,json:async()=>body};};
 const location={_hash:'',get hash(){return this._hash;},set hash(value){this._hash=value.startsWith('#')?value:'#'+value;window.dispatchEvent(new window.Event('hashchange'));}};
 vm.runInNewContext(read('admin-control.js'),{window,document,fetch,URL,Date,FormData,console,setTimeout,location,CustomEvent:window.CustomEvent,Event:window.Event});await settle();return {window,document,requests};}

test('admin control gates data on authorization',async()=>{const {document,requests}=await control(true);assert.equal(document.getElementById('controlContent').hidden,true);assert.equal(document.getElementById('controlLocked').hidden,false);assert.equal(document.querySelectorAll('.caseCard').length,0);assert.equal(requests.some(r=>r.url.includes('/insights')),false);});
test('admin feedback and AI render private content as text and include reasons',async()=>{const {document,window,requests}=await control();assert.equal(document.getElementById('controlContent').hidden,false);assert.equal(document.querySelectorAll('.caseCard h3 img').length,0);assert.equal(document.querySelectorAll('.caseCard script').length,0);assert.match(document.getElementById('caseList').textContent,/Долго ждал/);document.querySelector('[data-tab="feedback"]').dispatchEvent(new window.Event('click'));await settle();assert.match(document.getElementById('feedbackList').textContent,/<script>private/);assert.equal(document.querySelectorAll('#feedbackList form').length,0);document.getElementById('controlAnalyze').dispatchEvent(new window.Event('click'));await settle();assert.match(document.getElementById('controlInsights').textContent,/<script>Analysis/);assert.equal(document.querySelectorAll('#controlInsights script').length,0);assert.equal(document.getElementById('insightsSource').disabled,false);assert.equal(requests.filter(r=>r.url.includes('/insights?')).length,1);});
