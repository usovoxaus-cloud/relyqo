const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),acorn=require('acorn');
const {parseHTML}=require('linkedom');
const read=f=>fs.readFileSync('app/static/'+f,'utf8');
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));};
async function profile(status=200){
 const {document,window}=parseHTML(read('place.html'));const urls=[];
 const data={object_key:'relyqo:one',name:'Real <cafe>',address:'Street 1',category:'CAFE',category_label:'Кафе',profile_status:'VERIFIED_PARTNER',source:'RELYQO_PARTNER',verified_rating_count:2,relyqo_score:80,verified_visit_count:3,verified_last_rating_at:'2026-09-29T09:00:00Z',community_rating_count:1,community_score:70,community_last_rating_at:null,minimum_ratings:20,verified_metrics:{quality:80,service:80,cleanliness:80,value:80},metric_labels:{quality:'Качество',service:'Сервис',cleanliness:'Чистота',value:'Цена'}};
 vm.runInNewContext(read('place.js'),{document,window,URLSearchParams,location:{search:'?object_key=relyqo%3Aone&name=Fake&verified_score=100&verified_count=999'},localStorage:{getItem:()=>null,setItem(){}},fetch:async url=>{urls.push(url);return{ok:status===200,status,json:async()=>data};}});await settle();return{document,urls};
}
test('public profile takes identity and evidence from the server, ignoring fabricated URL scores',async()=>{
 const x=await profile();assert.deepEqual(x.urls,['/v1/public/place?object_key=relyqo%3Aone']);assert.equal(x.document.getElementById('name').textContent,'Real <cafe>');assert.equal(x.document.querySelector('#name cafe'),null);assert.equal(x.document.getElementById('verifiedScore').textContent,'80.0/100');assert.match(x.document.getElementById('verifiedCaption').textContent,/2 оценок.*предварительный.*3 принятых QR/);assert.equal(x.document.querySelector('a[href="/rate"]').textContent,'Оценить по QR');
});
test('a missing public profile cannot display the name, score or active rating link from the URL',async()=>{
 const x=await profile(404);assert.equal(x.document.getElementById('verifiedScore').textContent,'—');assert.equal(x.document.getElementById('name').textContent,'Организация');assert(x.document.getElementById('rate').classList.contains('hidden'));assert.match(x.document.getElementById('error').textContent,/не найдена/);
});
const nearby=read('nearby.js'),ast=acorn.parse(nearby,{ecmaVersion:'latest'});
function functions(names){return ast.body.filter(n=>n.type==='FunctionDeclaration'&&names.includes(n.id.name)).map(n=>nearby.slice(n.start,n.end)).join('\n');}
test('client sorting agrees with sample policy and never mixes counts between rating types',()=>{
 let type='ALL';const context={$:()=>({value:'rating'}),ratedFilterValue:()=>type};vm.createContext(context);vm.runInContext(functions(['scoreFor','displayedScore','displayedCount','sortRows','normalizeSearch']),context);
 const small={title:'Tiny',kind:'partner',verified_rating_count:2,relyqo_score:100,community_rating_count:150,community_score:90},large={title:'Established',kind:'partner',verified_rating_count:100,relyqo_score:85,community_rating_count:1,community_score:100};
 let rows=[small,large];context.sortRows(rows);assert.equal(rows[0],large);
 type='COMMUNITY';context.sortRows(rows);assert.equal(rows[0],small);
 assert.equal(context.normalizeSearch('Ўқув Фрегат'),context.normalizeSearch('o‘quv Fregat'));
});
test('add place submits without GPS and never silently assigns the visitor position to the business',async()=>{
 const {document}=parseHTML(read('nearby.html'));assert(!document.getElementById('addPlace').hasAttribute('disabled'));
 document.getElementById('manualForm').reset=()=>{};document.getElementById('manualDialog').close=()=>{};
 let handler,body;const form=document.getElementById('manualForm');form.addEventListener=(event,fn)=>handler=fn;
 const node=ast.body.find(n=>nearby.slice(n.start,n.end).startsWith('$("#manualForm").addEventListener("submit"'));
 const context={$:s=>document.querySelector(s),pendingManualLocation:null,pendingGooglePlaceId:null,currentCenter:{lat:41,lng:69},lastManualPlaces:[],showRatedOnly:true,pendingManualAction:'save',hasMapLocation:()=>false,reloadRatedCatalog(){},fetch:async(url,options)=>{body=JSON.parse(options.body);return{ok:true,json:async()=>({item:{id:'place',name:'New place',latitude:null,longitude:null}})}}};
 vm.runInNewContext(nearby.slice(node.start,node.end),context);const submit={disabled:false};await handler({preventDefault(){},submitter:submit});assert.equal(body.latitude,null);assert.equal(body.longitude,null);assert.equal(submit.disabled,false);assert.match(document.getElementById('status').textContent,/добавлено/);
});
