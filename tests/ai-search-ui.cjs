const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const {parseHTML}=require('linkedom');
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve}};
const reply=data=>({ok:true,json:async()=>data});
const data=JSON.parse(fs.readFileSync('app/static/uzbekistan.json','utf8'));
function place(id,name,city='Ташкент',country='UZ',region='Tashkent',lat=41.3,lng=69.2){return{id,displayName:name,formattedAddress:'Real street 1',primaryType:'dentist',googleMapsURI:'https://maps.google.com/',location:{lat:()=>lat,lng:()=>lng},addressComponents:[{types:['locality'],longText:city},{types:['administrative_area_level_1'],longText:region},{types:['country'],shortText:country}]};}
async function harness(options={}){
 const {document,window:events}=parseHTML(fs.readFileSync('app/static/nearby.html','utf8'));
 Object.defineProperty(events.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.hasAttribute('selected'))?.value||this.options[0]?.value||''},set(v){for(const o of this.options)o.removeAttribute('selected');[...this.options].find(o=>o.value===v)?.setAttribute('selected','')}});
 for(const select of document.querySelectorAll('select'))select.add=option=>select.append(option);
 const calls=[],timers=new Map();let timer=0,gps=0,maps=0;
 const google={maps:{importLibrary:async()=>({Place:{searchByText:async body=>{calls.push({places:body});return options.places?options.places(body):{places:[place('good','Real dental clinic'),place('foreign','Foreign','Almaty','KZ')]}}}}),Map:function(){maps++;}}};
 const window={google,relyqoCategoriesReady:Promise.resolve([]),setTimeout:(fn,delay)=>{timers.set(++timer,{fn,delay});return timer},clearTimeout:id=>timers.delete(id)};
 const context={document,window,google,Option:function(text,value=text){const o=document.createElement('option');o.textContent=text;o.value=value;return o},URLSearchParams,Intl,AbortController,Map,Set,setTimeout:window.setTimeout,clearTimeout:window.clearTimeout,localStorage:{getItem:()=>null,setItem(){}},navigator:{language:'ru',geolocation:{getCurrentPosition(){gps++}}},fetch:async(url,opts={})=>{
  const body=opts.body?JSON.parse(opts.body):null;calls.push({url,body});
  if(url.startsWith('/v1/public/rated-organizations')){if(options.localError)throw Error('Database unavailable');if(options.local)return options.local();return reply({items:[],total:0,geography:[],facets:{countries:['UZ','KZ'],cities:[]}});}
  if(url.startsWith('/static/uzbekistan.json'))return options.locations?options.locations():reply(data);
  if(url==='/v1/public/search/plan'){if(options.planError)throw new Error('signal is aborted without reason');return options.plan?options.plan(body):reply({country_code:'UZ',text_query:'детская стоматология, Ташкент, Узбекистан',category:'DENTAL',ai_generated:true});}
  throw Error('Unexpected '+url);
 }};
 vm.runInNewContext(fs.readFileSync('app/static/nearby.js','utf8'),context);vm.runInNewContext(fs.readFileSync('app/static/ai-search.js','utf8'),context);await settle();
 async function choose(id,value){document.querySelector(id).value=value;document.querySelector(id).dispatchEvent(new events.Event('change'));await settle()}
 async function runSearch(){const pending=[...timers].find(([id,t])=>t.delay===350);assert(pending,'automatic search was scheduled');timers.delete(pending[0]);pending[1].fn();await settle()}
 return{document,window,context,events,calls,choose,runSearch,counts:()=>({gps,maps})};
}
test('Uzbekistan is fixed, all 14 regions are available before business data, and cities follow the region',async()=>{
 const x=await harness({localError:true});
 assert.equal(x.document.querySelector('#ratedCountry').value,'UZ');assert.equal(x.document.querySelector('#ratedCountry').type,'hidden');
 assert.equal(x.document.querySelector('#ratedRegion').options.length,15);
 await x.choose('#ratedRegion','10');assert.match(x.document.querySelector('#ratedCity').textContent,/Самарканд/);assert.doesNotMatch(x.document.querySelector('#ratedCity').textContent,/Ташкент|Алматы/);
 await x.choose('#ratedCity','Samarkand');await x.choose('#ratedRegion','13');assert.equal(x.document.querySelector('#ratedCity').value,'ALL');assert.match(x.document.querySelector('#ratedCity').textContent,/Ташкент/);assert.doesNotMatch(x.document.querySelector('#ratedCity').textContent,/Самарканд/);
 assert(!x.calls.some(c=>c.url==='/v1/public/search/cities/recommend'));
});
test('late geographic load preserves current region rather than resetting it',async()=>{
 const slow=deferred(),x=await harness({locations:()=>slow.promise});await x.choose('#ratedRegion','09');slow.resolve(reply(data));await settle();
 assert.equal(x.document.querySelector('#ratedRegion').value,'09');assert.match(x.document.querySelector('#ratedCity').textContent,/Нукус/);assert.doesNotMatch(x.document.querySelector('#ratedCity').textContent,/Ташкент/);
});
test('initial loading is not presented as an empty search result',async()=>{
 const local=deferred(),x=await harness({local:()=>local.promise});
 assert.match(x.document.querySelector('#results').textContent,/Ищем подходящие организации/);
 assert.doesNotMatch(x.document.querySelector('#results').textContent,/нет организаций|Каталог пополняется/);
 local.resolve(reply({items:[],total:0,facets:{countries:['UZ'],cities:[]}}));await settle();
 assert.doesNotMatch(x.document.querySelector('#results').textContent,/Ищем подходящие организации/);
});
test('ordinary results render before the AI planner finishes, without GPS or writes',async()=>{
 const plan=deferred(),x=await harness({plan:()=>plan.promise});await x.choose('#ratedRegion','13');await x.choose('#ratedCity','Tashkent');x.document.querySelector('#catalogQuery').value='вылечить зуб ребёнку';await x.choose('#ratedCategory','HEALTH');await x.runSearch();
 assert.deepEqual(x.counts(),{gps:0,maps:0});assert.match(x.document.querySelector('#results').textContent,/Real dental clinic/);assert.doesNotMatch(x.document.querySelector('#results').textContent,/Foreign/);
 assert(x.calls.some(c=>c.url==='/v1/public/search/plan'));assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'));
 plan.resolve(reply({text_query:'детская стоматология, Ташкент, Узбекистан',ai_generated:true}));await settle();assert.match(x.document.querySelector('#citySearchStatus').textContent,/ИИ уточнил/);
});
test('missing or differently named locality does not erase nearby places; foreign or distant records are excluded',async()=>{
 const x=await harness({places:()=>({places:[place('district','District-address clinic','Chilonzor tumani'),place('distant','Distant','Ташкент','UZ','Tashkent',42,60),place('foreign','Foreign','Ташкент','KZ')]})});await x.choose('#ratedRegion','13');await x.choose('#ratedCity','Tashkent');await x.runSearch();
 assert.match(x.document.querySelector('#results').textContent,/District-address clinic/);assert.doesNotMatch(x.document.querySelector('#results').textContent,/Distant|Foreign/);
});
test('whole-region search works without choosing a city and separates Tashkent city from its region',async()=>{
 const x=await harness({places:()=>({places:[place('region','Chirchiq clinic','Чирчик','UZ','Tashkent Region',41.46,69.58),place('capital','Capital clinic')]})});await x.choose('#ratedRegion','14');await x.runSearch();
 assert.equal(x.document.querySelector('#ratedCity').value,'ALL');assert.match(x.document.querySelector('#results').textContent,/Chirchiq clinic/);assert.doesNotMatch(x.document.querySelector('#results').textContent,/Capital clinic/);
 assert(x.calls.some(c=>c.url?.includes('region_code=14')));
});
test('late business results cannot leak into another region',async()=>{
 const old=deferred(),x=await harness({places:body=>body.textQuery.includes('Ташкент')?old.promise:{places:[place('new','Nukus service','Нукус','UZ','Karakalpakstan',42.46,59.6)]}});
 await x.choose('#ratedRegion','13');await x.runSearch();await x.choose('#ratedRegion','09');await x.runSearch();old.resolve({places:[place('old','Old Tashkent service')]});await settle();
 assert.match(x.document.querySelector('#results').textContent,/Nukus service/);assert.doesNotMatch(x.document.querySelector('#results').textContent,/Old Tashkent service/);
});
test('database failure and planner failure cannot prevent live provider results',async()=>{
 const x=await harness({localError:true,planError:true});x.document.querySelector('#catalogQuery').value='стоматология';await x.choose('#ratedRegion','13');await x.runSearch();
 assert.match(x.document.querySelector('#results').textContent,/Real dental clinic/);assert.match(x.document.querySelector('#citySearchStatus').textContent,/обычный поиск работает/);assert.doesNotMatch(x.document.querySelector('#citySearchStatus').textContent,/aborted|signal/);
});
test('unsuccessful AI refinement keeps the already visible ordinary results',async()=>{
 const x=await harness({places:body=>({places:body.textQuery.startsWith('детская')?[]:[place('good','Real dental clinic')]})});x.document.querySelector('#catalogQuery').value='помощь с зубом';await x.choose('#ratedRegion','13');await x.runSearch();
 assert.match(x.document.querySelector('#results').textContent,/Real dental clinic/);assert.match(x.document.querySelector('#citySearchStatus').textContent,/Показаны результаты обычного поиска/);
});
