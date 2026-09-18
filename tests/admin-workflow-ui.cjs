const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {parseHTML}=require('linkedom');
const read=name=>fs.readFileSync('app/static/'+name,'utf8');
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};
function dom(html){const {window,document}=parseHTML(html);Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.selected)?.value??this.options[0]?.value??'';},set(v){for(const o of this.options)o.selected=o.value===String(v);}});return {window,document};}
const response=(d,status=200)=>({ok:status<400,status,json:async()=>d});

test('notifications are private, display untrusted names as text and persist a read receipt',async()=>{
 const {window,document}=dom('<html><body><main></main></body></html>');let marked=false;const sent=[];
 vm.runInNewContext(read('admin-notifications.js'),{window,document,console,setInterval:()=>0,fetch:async(url,options={})=>{sent.push({url,options});if(url.endsWith('/read')){marked=true;return response({ok:true});}return response({unread:marked?0:1,items:[{key:'application:x',title:'Новая заявка организации',organization:'<img src=x onerror=alert(1)>',read:marked,href:'/admin/control#applications'}]});}});
 await settle();assert.equal(document.querySelector('.adminNotifications').hidden,false);assert.equal(document.querySelectorAll('.notificationCard img').length,0);assert.match(document.querySelector('.notificationCard p').textContent,/<img/);
 document.querySelector('.notificationCard button').dispatchEvent(new window.Event('click'));await settle();assert.equal(document.querySelector('.notificationCard').dataset.read,'true');assert.deepEqual(JSON.parse(sent.find(r=>r.url.endsWith('/read')).options.body),{keys:['application:x']});
});

test('unauthenticated notifications reveal no list or count',async()=>{
 const {window,document}=dom('<html><body><main></main></body></html>');vm.runInNewContext(read('admin-notifications.js'),{window,document,setInterval:()=>0,fetch:async()=>response({detail:'Login'},401)});await settle();assert.equal(document.querySelector('.adminNotifications').hidden,true);assert.equal(document.querySelectorAll('.notificationCard').length,0);
});

test('action creation preserves selected dates/source/scope and never executes draft text',async()=>{
 const {window,document}=dom(read('admin-control.html'));const requests=[];const rows=[];const $=id=>document.getElementById(id);
 const fetch=async(url,options={})=>{requests.push({url,options});if(url.startsWith('/v1/admin/analytics'))return response({organizations:[{key:'org:test',name:'Test organization'}]});if(options.method==='POST'){const b=JSON.parse(options.body);const row={...b,id:'one',status:'OPEN',version:1,filters:b,baseline:{included:12,satisfied_percent:50,dissatisfied:3}};rows.push(row);return response(row,201);}return response({items:rows,next_offset:null});};
 vm.runInNewContext(read('admin-actions.js'),{window,document,fetch,Date,location:{hash:''},console});
 document.dispatchEvent(new window.CustomEvent('relyqo:control-tab',{detail:'actions'}));await settle();
 $('actionTitle').value='Check waiting time';$('actionRecommendation').value='<script>alert("draft")</script>';$('actionSource').value='community';$('actionEntity').value='org:test';$('actionStart').value='2026-09-01';$('actionEnd').value='2026-09-10';
 const event=new window.Event('submit',{cancelable:true});event.submitter=$('actionForm').querySelector('button');$('actionForm').dispatchEvent(event);await settle();
 const saved=JSON.parse(requests.find(r=>r.options.method==='POST').options.body);assert.equal(saved.source,'community');assert.equal(saved.entity,'org:test');assert.equal(saved.end,'2026-09-10');assert.equal(document.querySelectorAll('#actionList script').length,0);assert.match($('actionList').textContent,/alert/);assert.match($('actionStatus').textContent,/сохранена/);
});

test('backup setup distinguishes awaiting receipt, overdue and recent client saves',async()=>{
 const {window,document}=dom(read('admin-control.html'));
 vm.runInNewContext(read('backup-client.js'),{window,document,Date,navigator:{clipboard:{writeText:async()=>{}}},setTimeout:()=>0,fetch:async()=>response({ok:true})});
 const status=document.getElementById('localBackupStatus');
 for(const [state,match] of [['awaiting_first_backup',/Ожидаем/],['recent',/подтвердил/],['overdue',/36 часов/],['disabled',/отключён/]]){
 document.dispatchEvent(new window.CustomEvent('relyqo:backup-status',{detail:{status:state,last_saved_at:null}}));assert.match(status.textContent,match);
 }
 const key=document.getElementById('backupClientKey');key.value='fixture-secret';document.getElementById('backupKeyBox').hidden=false;window.dispatchEvent(new window.Event('pagehide'));assert.equal(key.value,'');assert.equal(document.getElementById('backupKeyBox').hidden,true);
});
