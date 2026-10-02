const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
const reply=data=>({ok:true,json:async()=>data});
const locations=JSON.parse(fs.readFileSync('app/static/uzbekistan.json','utf8'));
const localPlace={kind:'manual',id:'fixture-local',name:'Test cafe',address:'Test street 1',country_code:'UZ',city:'Tashkent',category:'CAFE',latitude:41.301,longitude:69.201,distance_km:.14,community_count:0};
function externalPlace(id='fixture-google',country='UZ') {return {id,displayName:'Test map cafe',formattedAddress:'Test street 2',primaryType:'cafe',googleMapsURI:'https://maps.google.com/',rating:4.2,userRatingCount:25,attributions:[],location:{lat:()=>41.302,lng:()=>69.202},addressComponents:[{types:['country'],shortText:country},{types:['locality'],longText:'Tashkent'},{types:['administrative_area_level_1'],longText:'Tashkent'}]};}
async function harness(options={}) {
  const {document,window:events}=parseHTML(fs.readFileSync('app/static/nearby.html','utf8'));
  if(options.uz)document.documentElement.lang='uz';
  Object.defineProperty(events.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.hasAttribute('selected'))?.value||this.options[0]?.value||''},set(value){for(const o of this.options)o.removeAttribute('selected');[...this.options].find(o=>o.value===value)?.setAttribute('selected','');}});
  for(const select of document.querySelectorAll('select'))select.add=option=>select.append(option);
  events.HTMLElement.prototype.scrollIntoView=function(){this.dataset.scrolled='true';};
  document.getElementById('manualDialog').showModal=function(){this.open=true;};
  const calls=[],markers=[],timers=new Map(),stored=new Map();let timer=0,map,gps=0,permission;
  if(options.saved)stored.set('relyqo.consumer.place.v1',JSON.stringify(options.saved));
  const google={maps:{Map:function(root,config){map=this;this.center={...config.center};this.setCenter=p=>{this.center={...p};};this.setZoom=z=>{this.zoom=z;};this.getCenter=()=>({lat:()=>this.center.lat,lng:()=>this.center.lng});},Marker:function(config){Object.assign(this,config);this.listeners={};this.addListener=(event,fn)=>{this.listeners[event]=fn;};this.setMap=value=>{this.map=value;};markers.push(this);},importLibrary:async()=>({SearchNearbyRankPreference:{DISTANCE:'DISTANCE',POPULARITY:'POPULARITY'},Place:{searchNearby:async body=>{calls.push({nearby:body});return options.nearby?options.nearby(body):{places:[externalPlace(),externalPlace('foreign','KZ')]};},searchByText:async body=>{calls.push({text:body});return {places:[externalPlace()]};}}})}};
  const window={google:options.noGoogle?undefined:google,relyqoCategoriesReady:Promise.resolve([]),setTimeout:(fn,delay)=>{timers.set(++timer,{fn,delay});return timer;},clearTimeout:id=>timers.delete(id)};
  const context={document,window,google,Event:events.Event,MutationObserver:events.MutationObserver,URLSearchParams,Intl,AbortController,Map,Set,location:{search:options.search??'?find=search',pathname:options.pathname||'/rate',href:'/rate'},Option:function(text,value=text){const o=document.createElement('option');o.textContent=text;o.value=value;return o;},setTimeout:window.setTimeout,clearTimeout:window.clearTimeout,localStorage:{getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value)},navigator:{language:'ru',geolocation:{getCurrentPosition(resolve,reject,settings){gps++;permission={resolve,reject,settings};if(options.gps==='denied')reject({code:1});else if(options.gps!=='pending')resolve({coords:{latitude:41.3,longitude:69.2,accuracy:options.accuracy??20}});}}},fetch:async(url,settings={})=>{
    const body=settings.body?JSON.parse(settings.body):null;calls.push({url,body,method:settings.method||'GET'});
    if(url.startsWith('/v1/public/rated-organizations'))return reply({items:options.localPlaces||[localPlace],total:1,geography:[],facets:{countries:['UZ'],cities:[]}});
    if(url.startsWith('/static/uzbekistan.json'))return reply(locations);
    if(url==='/v1/public/app-content')return reply({content:{ru:{title:'Generic search title',hint:'Generic search hint'}}});
    if(url==='/v1/public/manual-places/nearby')return reply({items:options.localPlaces||[localPlace]});
    if(url==='/v1/public/branches/nearby')return reply({items:[]});
    if(url==='/v1/public/maps-config')return reply({configured:false});
    if(url==='/v1/public/search/plan')return reply({ai_generated:false});
    throw Error('Unexpected request '+url);
  }};
  vm.createContext(context);
  for(const name of ['nearby','ai-search','consumer-search','rate-discovery'])vm.runInContext(fs.readFileSync(`app/static/${name}.js`,'utf8'),context,{filename:name+'.js'});
  await settle();
  const click=async selector=>{document.querySelector(selector).click();await settle();};
  const type=async value=>{document.getElementById('catalogQuery').value=value;document.getElementById('catalogQuery').dispatchEvent(new events.Event('input'));await settle();};
  const runTimer=async delay=>{const entry=[...timers].find(([,value])=>value.delay===delay);assert(entry,`expected ${delay}ms timer`);timers.delete(entry[0]);entry[1].fn();await settle();};
  return {document,window,context,events,calls,markers,stored,timers,click,type,runTimer,gps:()=>gps,map:()=>map,permission:()=>permission};
}

test('rating name search preserves the query and leads to the selected organization without GPS or writes',async()=>{
  const x=await harness({search:'?find=search&q=Test'});
  assert.equal(x.document.querySelector('.consumerTitle').textContent,'Какую организацию оценим?');
  assert.equal(x.document.getElementById('catalogQuery').value,'Test');
  assert.equal(x.gps(),0);assert.equal(x.map(),undefined);
  assert(x.calls.some(c=>c.url?.includes('q=Test')));
  const link=x.document.querySelector('#place-manual-fixture-local .rateLink');
  const url=new URL(link.getAttribute('href'),'https://example.test');assert.equal(url.pathname,'/community-rate');assert.equal(url.searchParams.get('object_key'),'manual:fixture-local');
  assert(!x.calls.some(c=>c.method!=='GET'));
  assert.equal(x.document.querySelector('.ratingDiscoveryActions a').href,'/rate?find=qr');
  await x.runTimer(350);
  assert(x.calls.some(c=>c.text?.fields.includes('rating')&&c.text.fields.includes('userRatingCount')));
});

test('nearby requests permission once, uses real coordinates and opens external selection without saving a rating',async()=>{
  const x=await harness({search:'?find=nearby'});
  assert.equal(x.gps(),1);assert.equal(x.permission().settings.timeout,12000);
  const call=x.calls.find(c=>c.url==='/v1/public/manual-places/nearby');assert.equal(call.body.latitude,41.3);assert.equal(call.body.longitude,69.2);
  assert.equal(x.document.getElementById('sortMode').value,'distance');
  assert.equal(x.calls.find(c=>c.nearby).nearby.rankPreference,'DISTANCE');
  assert(x.document.querySelector('#place-external-fixture-google'));
  assert.equal(x.document.querySelector('#place-external-foreign'),null);
  const marker=x.markers.findLast(m=>m.map&&m.title?.startsWith('Test map cafe'));
  marker.listeners.click();assert(x.document.getElementById('place-external-fixture-google').classList.contains('highlight'));
  await x.click('#place-external-fixture-google .rateLink');
  assert(x.document.getElementById('manualDialog').open);assert.equal(x.document.getElementById('manualName').value,'Test map cafe');
  assert.equal(x.document.querySelector('#manualForm [type=submit]').textContent,'Продолжить к оценке');
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'||c.url?.includes('ratings')));
  assert(![...x.stored.values()].some(value=>value.includes('41.3')||value.includes('latitude')));
});

test('denied GPS keeps a usable name search and manual map selection',async()=>{
  const x=await harness({search:'?find=nearby',gps:'denied'});
  assert.match(x.document.getElementById('error').textContent,/Доступ к геолокации запрещён/);
  assert.match(x.document.getElementById('status').textContent,/по названию/);
  assert(x.document.querySelector('#place-manual-fixture-local .rateLink'));
  assert.equal(x.document.getElementById('locate').disabled,false);
  await x.click('#discoveryMap');assert(x.map());assert.equal(x.gps(),1);
  assert.equal(x.document.getElementById('searchCenterLabel').textContent,'Центр поиска');
});

test('map mode needs no GPS, lets a user search a moved map and does not snap back on a redraw',async()=>{
  const x=await harness({search:'?find=map'});assert.equal(x.gps(),0);assert(x.map());
  assert.equal(x.document.getElementById('searchMapArea').disabled,false);
  x.map().center={lat:39.654,lng:66.976};
  vm.runInContext('renderAll()',x.context);
  assert.equal(x.map().center.lat,39.654);
  await x.click('#searchMapArea');
  const call=x.calls.findLast(c=>c.url==='/v1/public/manual-places/nearby');
  assert.equal(call.body.latitude,39.654);assert.equal(call.body.longitude,66.976);assert.equal(x.gps(),0);
  assert.equal(x.document.getElementById('searchCenterLabel').textContent,'Центр поиска');
  x.map().center={lat:50,lng:69};await x.click('#searchMapArea');
  assert.match(x.document.getElementById('error').textContent,/Узбекистане/);
});

test('stored city is restored before the chosen map or nearby mode starts',async()=>{
  const saved={region:'10',city:'Samarkand'};
  const x=await harness({search:'?find=map',saved});assert(x.map());
  assert.equal(x.document.getElementById('ratedCity').value,'Samarkand');
  const city=locations.cities.find(c=>c.city==='Samarkand');assert.equal(x.map().center.lat,city.latitude);
  const y=await harness({search:'?find=nearby',saved});assert.equal(y.gps(),1);assert(y.map());
});

test('late geolocation cannot replace a name search started while permission is pending',async()=>{
  const x=await harness({search:'?find=nearby',gps:'pending'});assert.equal(x.gps(),1);
  await x.type('Test');await x.runTimer(250);
  x.permission().resolve({coords:{latitude:42,longitude:60}});await settle();
  assert(!x.calls.some(c=>c.url?.endsWith('/nearby')));assert.equal(x.map(),undefined);
  assert.equal(x.document.getElementById('catalogQuery').value,'Test');assert(x.document.body.classList.contains('directoryMode'));
});

test('unavailable maps still leave own organizations usable and explain the fallback',async()=>{
  const x=await harness({search:'?find=map',noGoogle:true});
  assert.equal(x.document.getElementById('searchMapArea').disabled,true);
  assert(x.document.querySelector('#place-manual-fixture-local .rateLink'));
  assert.match(x.document.getElementById('error').textContent,/Google Карта не загрузилась/);assert.equal(x.gps(),0);
});

test('Uzbek entry and existing ordinary search remain distinct',async()=>{
  const x=await harness({search:'?find=search',uz:true});
  assert.equal(x.document.querySelector('.consumerTitle').textContent,'Qaysi tashkilotni baholaymiz?');
  assert.equal(x.document.getElementById('discoveryMap').textContent,'Xaritadan tanlash');
  const normal=await harness({search:'?find=unsupported'});assert(!normal.document.body.classList.contains('ratingDiscovery'));
  assert.equal(normal.document.getElementById('discoveryMap'),null);assert.equal(normal.gps(),0);
});

const atVenue=(id,latitude=41.3001)=>({...localPlace,id,name:`Fixture ${id}`,latitude});
test('entering Rate automatically locates once using a fresh fix and a small search area',async()=>{
  const x=await harness({search:'',localPlaces:[atVenue('here',41.3)],nearby:()=>({places:[]})});
  assert.equal(x.gps(),1);assert.equal(x.permission().settings.maximumAge,0);
  assert.equal(x.permission().settings.enableHighAccuracy,true);
  assert.equal(x.calls.find(c=>c.url==='/v1/public/manual-places/nearby').body.radius_km,.5);
  assert.equal(x.calls.find(c=>c.nearby).nearby.locationRestriction.radius,500);
  assert.equal(x.document.getElementById('discoveryHere').getAttribute('aria-pressed'),'true');
  assert.match(x.document.getElementById('currentPlaceMessage').textContent,/20 м/);
  const link=x.document.querySelector('#currentPlaceCandidates a');
  assert.equal(link.textContent,'Я здесь — оценить');
  assert.equal(new URL(link.getAttribute('href'),'https://example.test').searchParams.get('object_key'),'manual:here');
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'||c.url?.includes('/ratings')));
  assert(![...x.stored.values()].some(value=>/latitude|longitude|accuracy|41\.3/.test(value)));
});

test('several organizations in the same building require a consumer choice; far places are not guessed',async()=>{
  const rows=[atVenue('a'),atVenue('b'),atVenue('far',41.4)].map(item=>({...item,longitude:69.2}));
  const x=await harness({search:'?find=here',localPlaces:rows,nearby:()=>({places:[]})});
  assert.equal(x.document.querySelectorAll('.currentPlaceCandidate').length,2);
  assert.match(x.document.getElementById('currentPlaceTitle').textContent,/одном из этих мест/);
  assert(!x.document.getElementById('currentPlaceCandidates').textContent.includes('Fixture far'));
  assert.equal(x.context.location.href,'/rate');
  const y=await harness({search:'?find=here',localPlaces:[rows[2]],nearby:()=>({places:[]})});
  assert.equal(y.document.querySelectorAll('.currentPlaceCandidate').length,0);
  assert.match(y.document.getElementById('currentPlaceMessage').textContent,/ничего не найдено/);
});

test('poor GPS accuracy never claims to have identified the current organization',async()=>{
  const x=await harness({search:'?find=here',accuracy:2000,localPlaces:[atVenue('a')],nearby:()=>({places:[]})});
  assert.match(x.document.getElementById('currentPlaceMessage').textContent,/2000 м.*Не удалось точно определить/);
  assert.equal(x.document.getElementById('currentPlaceTitle').textContent,'Организации возле вас');
  assert.equal(x.document.querySelectorAll('.currentPlaceCandidate').length,1);
});

test('denied current-location permission offers other methods and does not repeat the request',async()=>{
  const x=await harness({search:'',gps:'denied'});assert.equal(x.gps(),1);
  assert.match(x.document.getElementById('error').textContent,/геолокации запрещён/);
  assert.equal(x.document.getElementById('discoveryHere').disabled,false);
  assert(x.document.getElementById('currentPlace').classList.contains('hidden'));
  await x.click('#discoveryByName');assert.equal(x.gps(),1);
  await x.click('#discoveryMap');assert.equal(x.gps(),1);assert(x.map());
});

test('a pending current-location fix is discarded after switching to manual map selection',async()=>{
  const x=await harness({search:'',gps:'pending'});
  await x.click('#discoveryMap');const before=x.calls.filter(c=>c.url?.endsWith('/nearby')).length;
  x.permission().resolve({coords:{latitude:42,longitude:60,accuracy:10}});await settle();
  assert.equal(x.calls.filter(c=>c.url?.endsWith('/nearby')).length,before);
  assert(x.document.getElementById('currentPlace').classList.contains('hidden'));
  assert.equal(x.document.getElementById('searchCenterLabel').textContent,'Центр поиска');
});

test('late Google discovery updates current-place candidates without requiring a second GPS request',async()=>{
  let resolve;const pending=new Promise(r=>{resolve=r;});
  const x=await harness({search:'',localPlaces:[],nearby:()=>pending});
  assert.match(x.document.getElementById('currentPlaceMessage').textContent,/Ищем организации/);
  const place=externalPlace();place.location={lat:()=>41.3,lng:()=>69.2};
  resolve({places:[place]});await settle();
  assert.equal(x.gps(),1);assert.equal(x.document.querySelectorAll('.currentPlaceCandidate').length,1);
  await x.click('.currentPlaceCandidate button');assert(x.document.getElementById('manualDialog').open);
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'));
});

test('invalid geolocation never reaches the nearby endpoints',async()=>{
  const x=await harness({search:'',gps:'pending'});
  x.permission().resolve({coords:{latitude:NaN,longitude:69.2,accuracy:10}});await settle();
  assert(!x.calls.some(c=>c.url?.endsWith('/nearby')));
  assert.match(x.document.getElementById('error').textContent,/Не удалось определить местоположение/);
});
