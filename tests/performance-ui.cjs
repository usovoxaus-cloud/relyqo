const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('fs'),vm=require('vm'),acorn=require('acorn');
const {parseHTML}=require('linkedom');
const settle=async()=>{for(let i=0;i<5;i++)await new Promise(r=>setImmediate(r));};
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
const source=fs.readFileSync('app/static/nearby.js','utf8');
function functions(...names){return acorn.parse(source,{ecmaVersion:'latest'}).body.filter(n=>n.type==='FunctionDeclaration'&&names.includes(n.id.name)).map(n=>source.slice(n.start,n.end)).join('\n');}
function setup(){const map=deferred(),external=deferred(),status={textContent:''},renders=[],requests=[],errors=[];let name='first';
 const context={currentCenter:{lat:41,lng:69},catalogRequestId:0,lastPartners:[],lastManualPlaces:[],lastExternalPlaces:[],Promise,setTimeout,clearTimeout,AbortController,Error,
  $:id=>id==='#serviceCategory'?{value:'ALL'}:status,selectedRadius:()=>15,selectedLimit:()=>20,clearError(){},updateSearchScope(){},showError:x=>errors.push(x),loadGoogleMap:()=>map.promise,
  fetchNearby:async url=>{requests.push(url);return [{name:name+url}]},fetchExternalPlaces:()=>external.promise,
  renderAll:()=>renders.push({local:[...context.lastPartners,...context.lastManualPlaces],external:[...context.lastExternalPlaces]})};
 vm.runInNewContext(functions('withDeadline','refreshCatalog'),context);return {context,map,external,status,renders,requests,errors,setName:x=>name=x};}

test('own catalog renders and search returns while Google is still pending',async()=>{const x=setup();await x.context.refreshCatalog();assert.equal(x.requests.length,2);assert.equal(x.renders[0].local.length,2);assert.equal(x.renders[0].external.length,0);assert.match(x.status.textContent,/RELYQO загружены/);x.map.resolve(true);await settle();x.external.resolve([{name:'Google place'}]);await settle();assert.equal(x.renders.at(-1).external[0].name,'Google place');});
test('unavailable Google never suppresses own catalog results',async()=>{const x=setup();x.map.resolve(false);await x.context.refreshCatalog();await settle();assert.equal(x.renders.at(-1).local.length,2);assert.match(x.errors[0],/Google Карта не загрузилась/);});
test('late results from an older search cannot replace a newer search',async()=>{const x=setup();const oldExternal=deferred(),newExternal=deferred();let calls=0;x.context.fetchExternalPlaces=()=>++calls===1?oldExternal.promise:newExternal.promise;x.map.resolve(true);await x.context.refreshCatalog();await settle();x.setName('second');await x.context.refreshCatalog();await settle();newExternal.resolve([{name:'new'}]);await settle();oldExternal.resolve([{name:'old'}]);await settle();assert.equal(x.context.lastExternalPlaces[0].name,'new');assert.match(x.context.lastPartners[0].name,/second/);});
test('external deadline releases a pending provider call',async()=>{const x=setup();await assert.rejects(x.context.withDeadline(new Promise(()=>{}),5),/медленно/);});

test('admin starts cases without waiting for the public reason catalog',async()=>{const {window,document}=parseHTML(fs.readFileSync('app/static/admin-control.html','utf8'));const reasons=deferred(),urls=[];const context={window,document,URL,Date,setTimeout,FormData,location:{hash:''},CustomEvent:window.CustomEvent,fetch:async url=>{urls.push(url);if(url==='/v1/public/feedback-reasons')return reasons.promise;return {ok:true,status:200,json:async()=>({items:[],legacy:[],next_offset:null})};}};vm.runInNewContext(fs.readFileSync('app/static/admin-control.js','utf8'),context);await settle();assert( urls.some(url=>url.includes('/control/cases?')) );assert.equal(document.getElementById('controlContent').hidden,true);reasons.resolve({ok:true,status:200,json:async()=>({items:[]})});await settle();assert.equal(document.getElementById('controlContent').hidden,false);});

test('text search cancels background nearby results and ignores its own outdated response',async()=>{const x=setup();const answer=deferred(),input={value:'Coffee'},button={disabled:false};x.context.$=id=>id==='#catalogQuery'?input:id==='#catalogSearchButton'?button:id==='#serviceCategory'?{value:'ALL'}:x.status;x.context.showRatedOnly=false;x.context.remoteSearchQuery='';x.context.remoteSearchIds=new Set();x.context.navigator={language:'ru'};x.context.google={maps:{importLibrary:async()=>({Place:{searchByText:()=>answer.promise},SearchByTextRankPreference:{RELEVANCE:1}})}};x.context.externalPlaceItem=p=>p;vm.runInNewContext(functions('searchCatalog'),x.context);x.map.resolve(true);await x.context.refreshCatalog();const initial=x.context.catalogRequestId;const search=x.context.searchCatalog();await settle();assert(x.context.catalogRequestId>initial);x.external.resolve([{name:'nearby'}]);await settle();assert.equal(x.context.lastExternalPlaces.length,0);++x.context.catalogRequestId;answer.resolve({places:[{id:'text',distance:1}]});await search;assert.equal(x.context.lastExternalPlaces.length,0);assert.equal(button.disabled,false);});

async function deepLink(hash, denied=false) {
 const {window,document}=parseHTML(fs.readFileSync('app/static/admin-control.html','utf8'));const urls=[];
 const fetch=async url=>{urls.push(url);if(url.includes('/control/cases?')||url==='/v1/public/feedback-reasons')return new Promise(()=>{});return {ok:!denied,status:denied?403:200,json:async()=>denied?{detail:'Доступ запрещён'}:{database:'ok',mail_last_7_days:{},events:[],role:'CONSUMER'}};};
 vm.runInNewContext(fs.readFileSync('app/static/admin-control.js','utf8'),{window,document,fetch,location:{hash},CustomEvent:window.CustomEvent,Date});
 await settle();return {window,document,urls};
}
test('operations deep link loads one private endpoint without waiting for case lists',async()=>{
 const x=await deepLink('#operations');assert.deepEqual(x.urls,['/v1/admin/operations']);assert.equal(x.document.getElementById('controlContent').hidden,false);assert.equal(x.document.getElementById('operations').hidden,false);assert.equal(x.document.getElementById('cases').hidden,true);
});
test('denied operations deep link never reveals the admin controls',async()=>{
 const x=await deepLink('#operations',true);assert.equal(x.document.getElementById('controlContent').hidden,true);assert.equal(x.document.getElementById('controlLocked').hidden,false);
});
test('direct AI tab still requires an administrator and rejects a consumer session',async()=>{
 const x=await deepLink('#insights');assert.deepEqual(x.urls,['/v1/auth/me']);assert.equal(x.document.getElementById('controlContent').hidden,true);assert.equal(x.document.getElementById('controlLocked').hidden,false);
});
