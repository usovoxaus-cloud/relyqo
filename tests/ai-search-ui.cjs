const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const {parseHTML}=require('linkedom');
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve}};
const reply=data=>({ok:true,json:async()=>data});
const rows={UZ:[{id:'1',city:'Tashkent',label_ru:'Ташкент',aliases:['Ташкент','Tashkent'],latitude:41.3,longitude:69.2},{id:'2',city:'Nukus',label_ru:'Нукус',aliases:['Nukus','Нукус'],latitude:42.46,longitude:59.6}],KZ:[{id:'3',city:'Almaty',label_ru:'Алматы',aliases:['Almaty'],latitude:43.2,longitude:76.9}]};
function place(id,name,city='Ташкент',country='UZ'){return{id,displayName:name,formattedAddress:'Real street 1',primaryType:'dentist',googleMapsURI:'https://maps.google.com/',location:{lat:()=>41.3,lng:()=>69.2},addressComponents:[{types:['locality'],longText:city},{types:['country'],shortText:country}]};}
async function harness(options={}){
 const {document,window:events}=parseHTML(fs.readFileSync('app/static/nearby.html','utf8'));
 Object.defineProperty(events.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.hasAttribute('selected'))?.value||this.options[0]?.value||''},set(v){for(const o of this.options)o.removeAttribute('selected');[...this.options].find(o=>o.value===v)?.setAttribute('selected','')}});
 for(const select of document.querySelectorAll('select'))select.add=option=>select.append(option);
 const calls=[],timers=new Map();let timer=0,gps=0,maps=0;
 const google={maps:{importLibrary:async()=>({Place:{searchByText:async body=>{calls.push({places:body});return options.places?options.places(body):{places:[place('good','Real dental clinic'),place('foreign','Foreign','Almaty','KZ')]}}}}),Map:function(){maps++;}}};
 const window={google,relyqoCategoriesReady:Promise.resolve([]),setTimeout:(fn,delay)=>{timers.set(++timer,{fn,delay});return timer},clearTimeout:id=>timers.delete(id)};
 const context={document,window,google,Option:function(text,value=text){const o=document.createElement('option');o.textContent=text;o.value=value;return o},URLSearchParams,Intl,AbortController,Map,Set,setTimeout:window.setTimeout,clearTimeout:window.clearTimeout,localStorage:{getItem:()=>null,setItem(){}},navigator:{language:'ru',geolocation:{getCurrentPosition(){gps++}}},fetch:async(url,opts={})=>{
  const body=opts.body?JSON.parse(opts.body):null;calls.push({url,body});
  if(url.startsWith('/v1/public/rated-organizations'))return reply({items:[],total:0,geography:[],facets:{countries:['UZ','KZ'],cities:Object.entries(rows).flatMap(([country_code,cities])=>cities.map(c=>({...c,country_code})))}});
  if(url.startsWith('/v1/public/search/cities?')){const code=new URLSearchParams(url.split('?')[1]).get('country_code');return options.cities?options.cities(code):reply({items:rows[code]})}
  if(url==='/v1/public/search/cities/recommend')return options.recommend?options.recommend(body):reply({recommended_ids:rows[body.country_code].map(row=>row.id),ai_generated:true});
  if(url==='/v1/public/search/plan'){if(options.planError)throw new Error('signal is aborted without reason');return reply({country_code:body.country_code,city:rows[body.country_code].find(c=>c.city===body.city),text_query:'детская стоматология, '+body.city+', '+body.country_code,category:'DENTAL',ai_generated:true});}
  throw Error('Unexpected '+url);
 }};
 vm.runInNewContext(fs.readFileSync('app/static/nearby.js','utf8'),context);vm.runInNewContext(fs.readFileSync('app/static/ai-search.js','utf8'),context);await settle();
 async function choose(id,value){document.querySelector(id).value=value;document.querySelector(id).dispatchEvent(new events.Event('change'));await settle()}
 async function runSearch(){const pending=[...timers].find(([id,t])=>t.delay===350);assert(pending,'automatic search was scheduled');timers.delete(pending[0]);pending[1].fn();await settle()}
 return{document,window,context,events,calls,choose,runSearch,counts:()=>({gps,maps})};
}
test('country selection expands city dropdown, late AI ordering preserves the selected city',async()=>{
 const recommendation=deferred();const x=await harness({recommend:()=>recommendation.promise});
 assert.equal(x.document.querySelector('#directoryGeography'),null);assert.equal(x.document.querySelector('#directoryServices'),null);
 await x.choose('#ratedCountry','UZ');assert.match(x.document.querySelector('#ratedCity').textContent,/Нукус/);
 await x.choose('#ratedCity','Nukus');recommendation.resolve(reply({recommended_ids:['2','1'],ai_generated:true}));await settle();
 assert.equal(x.document.querySelector('#ratedCity').value,'Nukus');assert.equal(x.document.querySelector('#ratedCity').options[1].value,'Nukus');
});
test('late country data cannot replace a newly chosen country',async()=>{
 const old=deferred();const x=await harness({cities:code=>code==='UZ'?old.promise:reply({items:rows.KZ})});
 await x.choose('#ratedCountry','UZ');await x.choose('#ratedCountry','KZ');old.resolve(reply({items:rows.UZ}));await settle();
 assert.equal(x.document.querySelector('#ratedCountry').value,'KZ');assert.match(x.document.querySelector('#ratedCity').textContent,/Алматы/);assert.doesNotMatch(x.document.querySelector('#ratedCity').textContent,/Нукус/);
});
test('automatic AI city search returns real provider places without GPS, map construction or database writes',async()=>{
 const x=await harness();await x.choose('#ratedCountry','UZ');await x.choose('#ratedCity','Tashkent');await x.runSearch();
 assert.deepEqual(x.counts(),{gps:0,maps:0});assert.match(x.document.querySelector('#results').textContent,/Real dental clinic/);assert.doesNotMatch(x.document.querySelector('#results').textContent,/Foreign/);assert.match(x.document.querySelector('#citySearchStatus').textContent,/ИИ уточнил/);
 assert.equal(vm.runInNewContext('lastCityPlaces[0].category',x.context),'DENTAL');
 assert(x.calls.some(c=>c.url==='/v1/public/search/plan'));assert(x.calls.some(c=>c.places?.textQuery.includes('Tashkent')));assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'));
});
test('late business results cannot leak into another city',async()=>{
 const old=deferred();const x=await harness({places:body=>body.textQuery.includes('Tashkent')?old.promise:{places:[place('new','Nukus service','Нукус')]}});
 await x.choose('#ratedCountry','UZ');await x.choose('#ratedCity','Tashkent');await x.runSearch();await x.choose('#ratedCity','Nukus');await x.runSearch();old.resolve({places:[place('old','Old Tashkent service')]});await settle();
 assert.match(x.document.querySelector('#results').textContent,/Nukus service/);assert.doesNotMatch(x.document.querySelector('#results').textContent,/Old Tashkent service/);
});

test('planner timeout still searches real places and never exposes raw network errors',async()=>{
 const x=await harness({planError:true});await x.choose('#ratedCountry','UZ');await x.choose('#ratedCity','Tashkent');await x.runSearch();
 assert.match(x.document.querySelector('#results').textContent,/Real dental clinic/);
 assert.match(x.document.querySelector('#citySearchStatus').textContent,/ИИ сейчас недоступен/);
 assert.doesNotMatch(x.document.querySelector('#citySearchStatus').textContent,/aborted|signal/);
 assert(x.calls.some(c=>c.places?.textQuery.endsWith(', Tashkent, UZ')));
});
