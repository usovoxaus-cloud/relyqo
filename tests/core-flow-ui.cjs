const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),acorn=require('acorn');
const {parseHTML}=require('linkedom');
const read=name=>fs.readFileSync('app/static/'+name,'utf8');
const settle=async()=>{for(let i=0;i<6;i++)await new Promise(r=>setImmediate(r));};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}};
const reply=data=>({ok:true,status:200,json:async()=>data});
function dom(name){const {document,window}=parseHTML(read(name));Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.selected)?.value??this.options[0]?.value??''},set(value){for(const o of this.options)o.selected=o.value===String(value)}});return{document,window};}
function photoHarness(document,window){
 const readers=[],errors=[];class Reader{constructor(){readers.push(this)}readAsDataURL(){}finish(value){this.result=value;this.onload()}}
 const context={document,window,FileReader:Reader,Error};vm.runInNewContext(read('rating-photo.js'),context);
 const input=document.querySelector('#photo'),preview=document.querySelector('#photoPreview');
 const choose=(type='image/jpeg',size=50)=>{Object.defineProperty(input,'files',{configurable:true,value:type?[{type,size}]:[]});input.dispatchEvent(new window.Event('change'));};
 const photo=window.relyqoRatingPhoto({input,preview,onError:message=>errors.push(message)});
 return{context,readers,errors,choose,photo,preview};
}
test('invalid replacement clears the previous attachment and preview',()=>{
 const x=photoHarness(...Object.values(dom('index.html')));x.choose();x.readers[0].finish('data:image/jpeg;base64,old');
 x.choose('image/jpeg',6*1024*1024);assert.equal(x.photo.value(),null);assert(x.preview.classList.contains('hidden'));assert.equal(x.preview.getAttribute('src'),null);assert.match(x.errors[0],/5 МБ/);
 x.choose('image/svg+xml');assert.equal(x.photo.value(),null);assert.match(x.errors[1],/JPEG/);
});
test('late file reads cannot replace newer photos, and pending reads cannot be submitted',()=>{
 const {document,window}=dom('index.html'),x=photoHarness(document,window);x.choose();x.choose();assert.throws(()=>x.photo.value(),/загружается/);x.readers[1].finish('new');x.readers[0].finish('old');assert.equal(x.photo.value(),'new');
 x.choose(null);assert.equal(x.photo.value(),null);x.readers[1].finish('late');assert.equal(x.photo.value(),null);
});
test('failed file reads leave no attachment and allow another choice',()=>{
 const {document,window}=dom('index.html'),x=photoHarness(document,window);x.choose();x.readers[0].onerror();assert.equal(x.photo.value(),null);assert.match(x.errors[0],/прочитать/);x.choose();x.readers[1].finish('retry');assert.equal(x.photo.value(),'retry');
});
function qrHarness(){
 const {document,window}=dom('index.html'),calls=[],verification=deferred(),submission=deferred();
 const create=document.createElement.bind(document);document.createElement=name=>{const e=create(name);if(name==='canvas')e.getContext=()=>null;return e;};
 window.relyqoCategoryGroup=()=>undefined;window.relyqoCategoriesReady=Promise.resolve();window.relyqoFeedback=()=>({});
 window.relyqoRatingPhoto=()=>({value:()=>null});
 const context={document,window,URL,URLSearchParams,location:{search:''},navigator:{},setTimeout,Error,fetch:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return url.includes('verify-token')?verification.promise:submission.promise;}};
 vm.runInNewContext(read('app.js'),context);return{document,window,context,calls,verification,submission};
}
test('QR pasted as a full link is accepted once, without overlapping verification requests',async()=>{
 const x=qrHarness();x.document.querySelector('#token').value='https://relyqo.onrender.com/?token=visit-secret';const b=x.document.querySelector('#verify');const a=b.onclick(),c=b.onclick();assert.equal(x.calls.length,1);assert.equal(x.calls[0].body.token,'visit-secret');assert.equal(b.disabled,true);
 x.verification.resolve(reply({visit_id:'visit-1',organization:{name:'Place',category:'OTHER'},branch:{name:'Branch'}}));await Promise.all([a,c]);assert.equal(x.document.querySelector('#rating').classList.contains('hidden'),false);await b.onclick();assert.equal(x.calls.length,1);
});
test('rating double clicks send once and failures preserve scores for a deliberate retry',async()=>{
 const x=qrHarness(),b=x.document.querySelector('#submit');x.document.querySelector('#overall').value='3';const a=b.onclick(),c=b.onclick();assert.equal(x.calls.length,1);assert.equal(b.disabled,true);x.submission.resolve({ok:false,status:503,json:async()=>{throw Error('html')}});await Promise.all([a,c]);assert.equal(b.disabled,false);assert.equal(x.document.querySelector('#overall').value,'3');assert.match(x.document.querySelector('#rateError').textContent,/Попробуйте позже/);
 x.context.fetch=async()=>{x.calls.push({});return reply({relyqo_score:50,ces_score:30,rating_count:1,status:'INCLUDED'})};await b.onclick();await b.onclick();assert.equal(x.calls.length,2);assert.equal(b.disabled,true);
});
test('business profile opens while category catalog is pending and retains its custom category',async()=>{
 const {document,window}=dom('business-owner.html'),categories=deferred(),requests=[];
 for(const form of document.querySelectorAll('form'))Object.defineProperty(form,'elements',{value:{namedItem:name=>form.querySelector(`[name="${name}"]`)}});
 window.relyqoCategoriesReady=categories.promise;window.relyqoCategoryLabel=()=>undefined;window.relyqoApplyCategoryOptions=()=>{};
 const context={document,window,FormData,location:{},navigator:{},fetch:async url=>{requests.push(url);return reply({username:'owner',organization_name:'School',category:'CUSTOM_SCHOOL',profile_status:'PUBLISHED',city:'Tashkent'})}};
 vm.runInNewContext([...document.querySelectorAll('script:not([src])')].map(s=>s.textContent).join('\n'),context);await settle();
 assert.deepEqual(requests,['/v1/business-owner/profile']);assert.equal(document.querySelector('#dashboard').classList.contains('hidden'),false);assert.equal(document.querySelector('#profileForm [name="category"]').value,'CUSTOM_SCHOOL');
 document.dispatchEvent(new window.Event('DOMContentLoaded'));window.relyqoCategoryLabel=code=>code==='CUSTOM_SCHOOL'?'Школа':undefined;categories.resolve([]);await settle();assert.match(document.querySelector('#organizationLead').textContent,/Школа/);assert.equal(document.querySelector('#profileForm [name="category"]').value,'CUSTOM_SCHOOL');
});
test('community categories update criteria without clearing scores; publishing cannot run twice',async()=>{
 const {document,window}=dom('community-rate.html'),categories=deferred(),submission=deferred(),requests=[];
 window.relyqoCategoryGroup=()=> 'HEALTH';window.relyqoCategoriesReady=categories.promise;window.relyqoFeedback=()=>({});window.relyqoRatingPhoto=()=>({value:()=>null});window.scrollTo=()=>{};
 const context={document,window,URLSearchParams,FormData,navigator:{},location:{pathname:'/community-rate',search:'?object_key=manual%3Aone&source=MANUAL&category=CUSTOM_VET'},fetch:async(url,options)=>{requests.push({url,options});return url==='/v1/auth/me'?reply({role:'CONSUMER',username:'reader'}):submission.promise;}};
 vm.runInNewContext([...document.querySelectorAll('script:not([src])')].map(s=>s.textContent).join('\n'),context);await settle();
 // linkedom does not reflect label.htmlFor into its HTML attribute.
 for(const label of document.querySelectorAll('#metrics label'))label.setAttribute('for',label.htmlFor);
 document.querySelector('#quality').value='4';document.dispatchEvent(new window.Event('DOMContentLoaded'));categories.resolve([]);await settle();assert.equal(document.querySelector('label[for="quality"]').textContent,'Качество помощи');assert.equal(document.querySelector('#quality').value,'4');
 const b=document.querySelector('#submit');b.dispatchEvent(new window.Event('click'));b.dispatchEvent(new window.Event('click'));assert.equal(requests.filter(r=>r.url==='/v1/community-ratings').length,1);assert.equal(JSON.parse(requests.at(-1).options.body).quality,4);
 submission.resolve(reply({community_score:40,rating_count:1}));await settle();b.dispatchEvent(new window.Event('click'));assert.equal(requests.filter(r=>r.url==='/v1/community-ratings').length,1);assert.equal(document.querySelector('#done').classList.contains('hidden'),false);
});
test('slow rated catalog responses cannot replace newer filters or unlock their loading button',async()=>{
 const source=read('nearby.js'),node=acorn.parse(source,{ecmaVersion:'latest'}).body.find(n=>n.type==='FunctionDeclaration'&&n.id.name==='loadRatedCatalog');
 const answers=[deferred(),deferred(),deferred()],button={},more={},q={value:'old'};let call=0;
 const context={URLSearchParams,ratedRequestId:0,ratedCatalogHasMore:true,lastRatedPlaces:[],ratedCatalogTotal:0,ratedCatalogFacets:{},ratedCatalogLoaded:false,
  $:id=>id==='#ratedOrganizationsTab'?button:id==='#ratedLoadMore'?more:id==='#catalogQuery'?q:{value:'0'},ratedFilterValue:()=> 'ALL',updateRatedLocationFilters(){},fetch:()=>answers[call++].promise};
 vm.runInNewContext(source.slice(node.start,node.end),context);const old=context.loadRatedCatalog();q.value='new';const fresh=context.loadRatedCatalog();answers[0].resolve(reply({items:[{name:'old'}]}));await old;assert.equal(button.disabled,true);assert.equal(context.lastRatedPlaces.length,0);answers[1].resolve(reply({items:[{name:'new'}],total:1}));await fresh;assert.equal(context.lastRatedPlaces[0].name,'new');assert.equal(button.disabled,false);
});
test('late geolocation denial cannot overwrite the catalog selected by the user',async()=>{
 const source=read('nearby.js'),node=acorn.parse(source,{ecmaVersion:'latest'}).body.find(n=>n.type==='FunctionDeclaration'&&n.id.name==='locate');
 const status={},button={},errors=[];let deny;
 const context={locationRequestId:0,$:id=>id==='#locate'?button:status,clearError(){},showError:m=>errors.push(m),navigator:{geolocation:{getCurrentPosition(resolve,reject){deny=reject}}}};
 vm.runInNewContext(source.slice(node.start,node.end),context);const pending=context.locate();++context.locationRequestId;status.textContent='Каталог с оценками загружен';deny({code:1});await pending;assert.equal(status.textContent,'Каталог с оценками загружен');assert.equal(errors.length,0);assert.equal(button.disabled,false);
});
