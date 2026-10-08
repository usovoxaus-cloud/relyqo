const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {parseHTML}=require('linkedom');
const read=name=>fs.readFileSync('app/static/'+name,'utf8');
const dictionary=JSON.parse(read('i18n-uz.json'));
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};
function dom(html){
 const {window,document}=parseHTML(html);
 Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.selected)?.value??this.options[0]?.value??'';},set(value){for(const o of this.options)o.selected=o.value===String(value);}});
 return {window,document};
}
function language(context){
 Object.assign(context,{navigator:{language:'ru'},localStorage:{getItem:()=>null,setItem(){}},AbortController,setTimeout,clearTimeout,MutationObserver:context.window.MutationObserver});
 vm.runInNewContext(read('i18n.js'),context);
}

for(const lang of ['ru','uz'])test(`rankings distinguish no ratings from a measured zero (${lang})`,async()=>{
 const {window,document}=dom(read('rankings.html'));
 window.relyqoCategoriesReady=Promise.resolve([]);window.relyqoApplyCategoryOptions=()=>{};
 const context={window,document,URLSearchParams,URL,Intl,console,history:{replaceState(){}},location:{search:'?lang='+lang,href:'https://relyqo.test/rankings?lang='+lang,protocol:'https:'},
  fetch:async url=>({ok:true,json:async()=>url.startsWith('/static/i18n-uz')?dictionary:url.includes('ranking-locations')?{countries:[],country_count:0,city_count:0}:{scope:'city',ranked_count:1,provisional_count:2,items:[
   {name:'No ratings',category:'EDUCATION',verified_rating_count:0,verified_score:0,eligible:false},
   {name:'Measured zero',category:'EDUCATION',verified_rating_count:20,verified_score:0,eligible:true,position:1},
   {name:'Measured result',category:'EDUCATION',verified_rating_count:4,verified_score:78.25,eligible:false}
  ]}})};
 language(context);
 const inline=[...document.querySelectorAll('script')].find(n=>!n.src&&n.textContent.includes('function render(data)'));
 vm.runInNewContext(inline.textContent,context);await window.relyqoLanguageReady;await settle();
 const scores=[...document.querySelectorAll('.row .score')];
 assert.equal(scores.length,3);
 assert.match(scores[0].textContent,lang==='uz'?/Baholar yo‘q/:/Нет оценок/);
 assert.doesNotMatch(scores[0].textContent,/0\.0\/100/);
 assert.match(scores[1].textContent,/0\.0\/100/);
 assert.match(scores[2].textContent,/78\.3\/100/);
 assert.equal(document.querySelectorAll('.row.unrated').length,0);
 assert.equal(document.querySelectorAll('.score.unrated').length,1);
 assert.equal(document.querySelectorAll('.row.provisional').length,2);
});

for(const lang of ['ru','uz'])test(`hosting recovery remains separate from an unsaved Windows copy (${lang})`,async()=>{
 const {window,document}=dom(read('admin-control.html'));
 const context={window,document,console,URL,URLSearchParams,Date,CustomEvent:window.CustomEvent,Event:window.Event,
  location:{hash:'#operations',search:'?lang='+lang,href:'https://relyqo.test/admin/control?lang='+lang+'#operations',protocol:'https:'},
  fetch:async url=>({ok:true,json:async()=>url.startsWith('/static/i18n-uz')?dictionary:{database:'ok',database_plan:'paid',database_expires_at:'2026-09-28',mail_configured:true,admin_email_verified:true,provider_backups:{status:'enabled',recovery_days:3,checked_at:'2026-10-08'},local_backups:{status:'awaiting_first_backup'},mail_last_7_days:{},events:[]}})};
 language(context);
 vm.runInNewContext(read('backup-client.js'),context);
 vm.runInNewContext(read('admin-control.js'),context);
 await window.relyqoLanguageReady;await settle();
 const summary=document.getElementById('operationsSummary').textContent;
 assert.doesNotMatch(summary,/2026-09-28/);
 assert.match(summary,/2026-10-08/);
 assert.match(summary,lang==='uz'?/Xostingda tiklash: yoqilgan/:/Восстановление у хостинга: включено/);
 assert.match(document.getElementById('localBackupStatus').textContent,lang==='uz'?/nusxa/:/первую сохранённую копию/);
 if(lang==='uz')assert.doesNotMatch(summary,/[А-Яа-яЁё]/);
});

test('unverified provider status never claims backups are enabled',async()=>{
 const {window,document}=dom(read('admin-control.html'));
 vm.runInNewContext(read('admin-control.js'),{window,document,Date,CustomEvent:window.CustomEvent,Event:window.Event,location:{hash:'#operations'},fetch:async()=>({ok:true,json:async()=>({database:'ok',mail_last_7_days:{},events:[],automatic_backups:'not_configured'})})});
 await settle();
 assert.match(document.getElementById('operationsSummary').textContent,/Восстановление у хостинга: не подтверждено/);
});
