const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
const reply=data=>({ok:true,json:async()=>data});
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
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
    if(url.endsWith('/nearby')&&options.localNearby)return options.localNearby(url,body);
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
  for(const url of ['/v1/public/manual-places/nearby','/v1/public/branches/nearby'])assert.equal(x.calls.find(c=>c.url===url).body.radius_km,.3);
  assert.equal(x.calls.find(c=>c.nearby).nearby.locationRestriction.radius,300);
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
  assert.match(x.document.getElementById('currentPlaceTitle').textContent,/300 м/);
  assert(!x.document.getElementById('currentPlaceCandidates').textContent.includes('Fixture far'));
  assert.equal(x.context.location.href,'/rate');
  const y=await harness({search:'?find=here',localPlaces:[rows[2]],nearby:()=>({places:[]})});
  assert.equal(y.document.querySelectorAll('.currentPlaceCandidate').length,0);
  assert.match(y.document.getElementById('currentPlaceMessage').textContent,/ничего не найдено/);
});

test('poor GPS accuracy never claims to have identified the current organization',async()=>{
  const x=await harness({search:'?find=here',accuracy:2000,localPlaces:[atVenue('a')],nearby:()=>({places:[]})});
  assert.match(x.document.getElementById('currentPlaceMessage').textContent,/2000 м.*GPS неточный.*радиус не расширяется/);
  assert.equal(x.document.getElementById('currentPlaceTitle').textContent,'Организации в радиусе 300 м');
  assert(x.calls.filter(c=>c.url?.endsWith('/nearby')).every(c=>c.body.radius_km===.3));
  assert(x.calls.filter(c=>c.nearby).every(c=>c.nearby.locationRestriction.radius===300));
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

const latitudeAt=meters=>41.3+meters/(6371008.8*Math.PI/180);
const localAt=meters=>({...localPlace,id:`local-${meters}`,name:`Local ${meters}`,latitude:latitudeAt(meters),longitude:69.2,distance_km:Math.round(meters/10)/100});
const googleAt=meters=>({...externalPlace(`google-${meters}`),displayName:`Google ${meters}`,location:{lat:()=>latitudeAt(meters),lng:()=>69.2}});
const names=x=>[...x.document.querySelectorAll('.currentPlaceCandidate h3')].map(n=>n.textContent);

test('300m boundary and distance order apply to every candidate, list card and marker without a five or twenty item cap',async()=>{
  const local=[299.99,150,300.01,5,290,200,120,80,300].map(localAt);
  const google=[300.01,300,299.99,250,225,201,199,175,151,149,125,100,75,60,40,20].map(googleAt);
  const x=await harness({search:'?find=here',localPlaces:local,nearby:()=>({places:google})});
  const expected=[...local.filter(p=>p.id!=='local-300.01').map(p=>({name:p.name,lat:p.latitude})),...google.filter(p=>p.id!=='google-300.01').map(p=>({name:p.displayName,lat:p.location.lat()}))].sort((a,b)=>a.lat-b.lat).map(p=>p.name);
  assert(expected.length>20);assert.deepEqual(names(x),expected);
  const rows=vm.runInContext('viewRows()',x.context);assert.equal(rows.length,expected.length);assert(rows.every(p=>p.distance<=.3+1e-9));
  assert.equal(x.document.querySelectorAll('#results .place').length,expected.length);
  const markers=x.markers.filter(m=>m.map&&m.title!=='Вы находитесь здесь');assert.equal(markers.length,expected.length);
  assert(markers.every(m=>m.position.lat<=latitudeAt(300)+1e-12));
  assert(!x.calls.some(c=>c.url&&c.method!=='GET'&&!c.url.endsWith('/nearby')));
  assert.match(x.document.querySelector('.currentPlaceNote').textContent,/до 20.*неполным/);
});

test('ready Google map and automatic results never wait for either local endpoint',async()=>{
  const branches=deferred(),manual=deferred(),google=deferred();
  const x=await harness({search:'',localNearby:url=>url.includes('/branches/')?branches.promise:manual.promise,nearby:()=>google.promise});
  assert(x.map());assert.equal(x.document.getElementById('map').classList.contains('hidden'),false);
  assert.match(x.document.getElementById('status').textContent,/300 м/);
  google.resolve({places:[googleAt(200)]});await settle();
  assert.deepEqual(names(x),['Google 200']);assert.equal(x.gps(),1);
  assert.equal(x.document.getElementById('discoveryHere').disabled,false);
  manual.resolve(reply({items:[localAt(100)]}));await settle();assert.deepEqual(names(x),['Local 100','Google 200']);
  branches.reject(Error('local unavailable'));await settle();assert.deepEqual(names(x),['Local 100','Google 200']);
  assert.equal(x.window.relyqoNearbyPending,false);assert.match(x.document.getElementById('error').textContent,/Часть каталога RELYQO недоступна/);
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'));
});

test('local failures before Google resolves do not invalidate successful Places results',async()=>{
  const google=deferred();
  const x=await harness({search:'',localNearby:()=>{throw Error('local offline');},nearby:()=>google.promise});
  assert.equal(x.window.relyqoNearbyState.localFailed,2);
  google.resolve({places:[googleAt(280)]});await settle();
  assert.deepEqual(names(x),['Google 280']);assert.equal(x.gps(),1);
  await x.click('.currentPlaceSelect');assert(x.document.getElementById('manualDialog').open);
  assert.equal(x.document.getElementById('manualName').value,'Google 280');
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'));
});

test('Google failure keeps local places 150–300m visible with an honest partial-result message',async()=>{
  const x=await harness({search:'',localPlaces:[localAt(280)],nearby:()=>{throw Error('Google offline');}});
  assert.deepEqual(names(x),['Local 280']);assert.match(x.document.getElementById('error').textContent,/Google.*недоступен/);
  assert.equal(x.window.relyqoNearbyPending,false);assert.equal(x.gps(),1);
});

test('late local and Google replies from an old fix cannot replace a newer search',async()=>{
  const local=deferred(),google=deferred();let fresh=false;
  const x=await harness({search:'',localNearby:url=>fresh?reply({items:url.includes('/manual-places/')?[localAt(80)]:[]}):local.promise,nearby:()=>fresh?{places:[googleAt(90)]}:google.promise});
  await x.click('#discoveryByName');fresh=true;await x.click('#discoveryHere');
  assert.deepEqual(names(x),['Local 80','Google 90']);
  local.resolve(reply({items:[localAt(10)]}));google.resolve({places:[googleAt(20)]});await settle();
  assert.deepEqual(names(x),['Local 80','Google 90']);assert.equal(x.gps(),2);
});

test('current-place scope stays separate from ordinary map settings and restores them on exit',async()=>{
  const x=await harness({search:'?find=map'});const radius=x.document.getElementById('radius'),limit=x.document.getElementById('resultLimit');
  radius.value='8';limit.value='50';await x.click('#discoveryHere');
  assert.equal(radius.value,'0.3');assert.equal(radius.disabled,true);assert.equal(limit.disabled,true);
  assert.equal(x.document.getElementById('sortMode').disabled,true);
  await editRadius(x,'750');assertScope(x,750);
  await x.click('#discoveryMap');assert.equal(radius.value,'8');assert.equal(limit.value,'50');assert.equal(radius.disabled,false);
  assert.equal(x.calls.filter(c=>c.url?.endsWith('/nearby')).at(-1).body.radius_km,8);
  await x.click('#discoveryHere');assertScope(x,750);
});

test('Uzbek current-place loading, empty, failure and low-accuracy messages describe 300m and provider limits',async()=>{
  const pending=deferred();const x=await harness({search:'',uz:true,accuracy:2000,localPlaces:[],nearby:()=>pending.promise});
  assert.match(x.document.getElementById('currentPlaceTitle').textContent,/300 m/);
  assert.match(x.document.getElementById('currentPlaceMessage').textContent,/GPS noaniq.*kengaytirilmaydi.*300 m.*izlayapmiz/);
  pending.resolve({places:[]});await settle();assert.match(x.document.getElementById('currentPlaceMessage').textContent,/300 m.*hech narsa topilmadi/);
  assert.match(x.document.querySelector('.currentPlaceNote').textContent,/20 tagacha.*to‘liq bo‘lmasligi/);
  const failed=await harness({search:'',uz:true,localNearby:()=>{throw Error('offline')},nearby:()=>{throw Error('offline')}});
  assert.match(failed.document.getElementById('currentPlaceMessage').textContent,/300 m radiusdagi barcha manbalarni yuklab bo‘lmadi/);
  assert(!failed.document.getElementById('currentPlaceMessage').textContent.includes('hech narsa topilmadi'));
});

async function editRadius(x,value,apply=true){
  const input=x.document.getElementById('currentRadiusMeters');input.value=value;input.dispatchEvent(new x.events.Event('input'));await settle();
  if(apply){x.document.querySelector('.ratingRadiusForm').dispatchEvent(new x.events.Event('submit',{cancelable:true}));await settle();}
}
const nearbyCalls=x=>x.calls.filter(c=>c.url?.endsWith('/nearby'));
function assertScope(x,meters){
  const local=nearbyCalls(x).slice(-2);assert.equal(local.length,2);assert(local.every(c=>c.body.radius_km===meters/1000));
  assert.equal(x.calls.filter(c=>c.nearby).at(-1).nearby.locationRestriction.radius,meters);
  assert.equal(x.document.getElementById('mapRadius').textContent,String(meters/1000));
}

test('1km preset updates both APIs and all views, includes its boundary, and does not request GPS again',async()=>{
  const local=[1100,1000,250,999.99,1000.01,800].map(localAt),google=[500,1000,1000.01].map(googleAt);
  const x=await harness({search:'',localPlaces:local,nearby:()=>({places:google})});
  assertScope(x,300);assert.equal(x.document.getElementById('currentRadiusMeters').value,'300');
  assert.deepEqual(names(x),['Local 250']);
  await x.click('[data-radius="1000"]');assertScope(x,1000);assert.equal(x.gps(),1);
  assert.deepEqual(names(x),['Local 250','Google 500','Local 800','Local 999.99','Local 1000','Google 1000']);
  assert.equal(x.document.querySelectorAll('#results .place').length,6);
  assert.equal(x.markers.filter(m=>m.map&&m.title!=='Вы находитесь здесь').length,6);
  assert(x.markers.filter(m=>m.map).every(m=>m.position.lat<=latitudeAt(1000)+1e-12));
  assert.match(x.document.getElementById('currentPlaceTitle').textContent,/1 км/);
  assert.match(x.document.getElementById('scopeHint').textContent,/1 км/);
  await x.click('[data-radius="300"]');assertScope(x,300);assert.deepEqual(names(x),['Local 250']);assert.equal(x.gps(),1);
});

test('custom 750m is applied explicitly, supports Enter, and excludes places beyond the unrounded boundary',async()=>{
  const x=await harness({search:'',localPlaces:[localAt(749.99),localAt(750),localAt(750.01)],nearby:()=>({places:[googleAt(600),googleAt(750),googleAt(750.01)]})});
  const count=nearbyCalls(x).length;
  for(const value of ['7','75','750'])await editRadius(x,value,false);
  assert.equal(nearbyCalls(x).length,count);
  const enter=new x.events.Event('keydown',{cancelable:true});enter.key='Enter';
  x.document.getElementById('currentRadiusMeters').dispatchEvent(enter);await settle();
  assertScope(x,750);assert.equal(x.gps(),1);
  assert.deepEqual(names(x),['Google 600','Local 749.99','Local 750','Google 750']);
  assert.match(x.document.getElementById('currentPlaceTitle').textContent,/750 м/);
  assert([...x.document.querySelectorAll('.ratingRadiusPresets button')].every(b=>b.getAttribute('aria-pressed')==='false'));
});

test('invalid radius drafts never search, request GPS, clamp silently or reset accepted results',async()=>{
  const x=await harness({search:''}),original=names(x),count=x.calls.length,gps=x.gps();
  for(const value of ['', ' ', '99','50001','-500','Infinity','NaN','abc','1e3']){
    await editRadius(x,value);await x.click('#discoveryHere');
    assert.equal(x.calls.length,count,value);assert.equal(x.gps(),gps,value);assert.deepEqual(names(x),original,value);
    assert.equal(x.document.getElementById('currentRadiusMeters').getAttribute('aria-invalid'),'true');
    assert.equal(x.document.getElementById('currentRadiusError').hidden,false);
    assert.equal(x.document.getElementById('mapRadius').textContent,'0.3');
  }
  await editRadius(x,'750');assertScope(x,750);assert.equal(x.document.getElementById('currentRadiusError').hidden,true);
});

test('radius remains usable while GPS is pending and the first requests use the latest chosen distance',async()=>{
  const x=await harness({search:'',gps:'pending'});
  await x.click('[data-radius="1000"]');await editRadius(x,'750');
  assert.equal(nearbyCalls(x).length,0);assert.equal(x.gps(),1);
  assert.equal(x.document.getElementById('currentRadiusMeters').disabled,false);
  assert.match(x.document.getElementById('currentPlaceMessage').textContent,/750 м/);
  assert.match(x.document.getElementById('results').textContent,/750 м/);
  x.permission().resolve({coords:{latitude:41.3,longitude:69.2,accuracy:20}});await settle();
  assertScope(x,750);assert.equal(nearbyCalls(x).length,2);assert.equal(x.gps(),1);
});

test('invalid draft during pending GPS prevents the initial search until corrected without another GPS prompt',async()=>{
  const x=await harness({search:'',gps:'pending'});await editRadius(x,'50001',false);
  x.permission().resolve({coords:{latitude:41.3,longitude:69.2,accuracy:20}});await settle();
  assert.equal(nearbyCalls(x).length,0);assert(!x.calls.some(c=>c.nearby));
  assert(!x.document.getElementById('results').textContent.includes('ничего не найдено'));
  await editRadius(x,'750');assertScope(x,750);assert.equal(x.gps(),1);
});

test('settings survive denied GPS without an automatic permission retry and fresh retry retains the chosen radius',async()=>{
  const x=await harness({search:'',gps:'pending'});await x.click('[data-radius="1000"]');
  x.permission().reject({code:1});await settle();await editRadius(x,'750');
  assert.equal(x.gps(),1);assert.equal(nearbyCalls(x).length,0);assert.equal(x.document.getElementById('currentRadiusMeters').disabled,false);
  await x.click('#discoveryHere');assert.equal(x.gps(),2);
  x.permission().resolve({coords:{latitude:41.3,longitude:69.2,accuracy:20}});await settle();assertScope(x,750);
  await x.click('#currentPlaceRetry');assert.equal(x.gps(),3);assert.equal(x.permission().settings.maximumAge,0);
  x.permission().resolve({coords:{latitude:41.301,longitude:69.201,accuracy:10}});await settle();
  assertScope(x,750);assert.equal(nearbyCalls(x).at(-1).body.latitude,41.301);
});

test('late local and Google results from a wider radius cannot replace a newer narrow search',async()=>{
  const wideLocal=deferred(),wideGoogle=deferred();
  const x=await harness({search:'',localNearby:(url,body)=>body.radius_km===1?wideLocal.promise:reply({items:url.includes('/manual-places/')?[localAt(150)]:[]}),nearby:body=>body.locationRestriction.radius===1000?wideGoogle.promise:{places:[googleAt(200)]}});
  await x.click('[data-radius="1000"]');await x.click('[data-radius="300"]');
  assert.deepEqual(names(x),['Local 150','Google 200']);
  wideLocal.resolve(reply({items:[localAt(850)]}));wideGoogle.resolve({places:[googleAt(900)]});await settle();
  assert.deepEqual(names(x),['Local 150','Google 200']);assertScope(x,300);assert.equal(x.gps(),1);
});

test('dynamic RU/UZ loading, empty, error and low-accuracy text use the chosen radius',async()=>{
  for(const uz of [false,true]){
    const answer=deferred();let failing=false;
    const x=await harness({search:'',uz,accuracy:2000,localPlaces:[],nearby:()=>failing?Promise.reject(Error('offline')):answer.promise});
    await x.click('[data-radius="1000"]');
    const unit=uz?'1 km':'1 км';
    for(const id of ['currentPlaceTitle','currentPlaceMessage','results','status','scopeHint'])assert(x.document.getElementById(id).textContent.includes(unit),id);
    assert.match(x.document.getElementById('currentPlaceMessage').textContent,uz?/kengaytirilmaydi/:/не расширяется/);
    answer.resolve({places:[]});await settle();
    assert(x.document.getElementById('results').textContent.includes(unit));
    assert.match(x.document.getElementById('currentPlaceMessage').textContent,uz?/hech narsa topilmadi/:/ничего не найдено/);
    failing=true;await editRadius(x,'750');
    for(const id of ['currentPlaceTitle','currentPlaceMessage','results','error'])assert(x.document.getElementById(id).textContent.includes(uz?'750 m':'750 м'),id);
  }
});

test('minimum and maximum custom radii are sent without Google clamping or extra search zones',async()=>{
  const x=await harness({search:''});
  for(const meters of [100,50000]){
    const count=x.calls.filter(c=>c.nearby).length;await editRadius(x,String(meters));
    assertScope(x,meters);assert.equal(x.calls.filter(c=>c.nearby).length,count+1);
  }
  assert.equal(x.gps(),1);
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'||c.url?.includes('/ratings')));
});

test('pending GPS immediately synchronizes 300m labels and restores the prior scope before a new search finishes',async()=>{
  const local=deferred(),google=deferred();
  const x=await harness({search:'?find=search',gps:'pending',localNearby:()=>local.promise,nearby:()=>google.promise});
  x.document.getElementById('radius').value='8';
  await x.click('#discoveryHere');
  assert(x.document.body.classList.contains('findingCurrentPlace'));
  assert.equal(x.document.getElementById('mapRadius').textContent,'0.3');
  assert.match(x.document.getElementById('scopeHint').textContent,/300 м/);
  assert.match(x.document.getElementById('results').textContent,/Ожидаем местоположение.*300 м/);
  assert(!x.document.getElementById('results').textContent.includes('не найдены'));
  assert(!x.calls.some(c=>c.url?.endsWith('/nearby')));
  await x.click('#discoveryMap');
  assert(!x.document.body.classList.contains('findingCurrentPlace'));
  assert.equal(x.document.getElementById('mapRadius').textContent,'8');
  assert.match(x.document.getElementById('scopeHint').textContent,/8 км/);
  x.permission().reject({code:1});await settle();
  assert.equal(x.document.getElementById('mapRadius').textContent,'8');assert.equal(x.gps(),1);
  local.resolve(reply({items:[]}));google.resolve({places:[]});await settle();
});

test('denied GPS restores ordinary labels when leaving current-place mode without repeating permission',async()=>{
  const x=await harness({search:'',gps:'pending'});
  assert.equal(x.document.getElementById('mapRadius').textContent,'0.3');
  x.permission().reject({code:1});await settle();
  assert(!x.document.body.classList.contains('findingCurrentPlace'));
  assert(x.document.getElementById('currentPlace').classList.contains('hidden'));
  assert.equal(x.document.getElementById('mapRadius').textContent,'15');
  assert.match(x.document.getElementById('scopeHint').textContent,/15 км/);
  assert.match(x.document.getElementById('error').textContent,/геолокации запрещён/);
  assert(!x.document.getElementById('results').textContent.includes('Ожидаем местоположение'));
  assert(x.document.querySelector('#place-manual-fixture-local .rateLink'));
  assert.equal(x.gps(),1);assert(!x.calls.some(c=>c.url?.endsWith('/nearby')));
});

test('current-place list waits for GPS and outstanding sources in RU/UZ, then shows a completed empty result',async()=>{
  for(const uz of [false,true]){
    const google=deferred();
    const x=await harness({search:'',gps:'pending',uz,localPlaces:[],nearby:()=>google.promise});
    const results=x.document.getElementById('results');
    assert.match(results.textContent,uz?/joylashuvni kutyapmiz/:/Ожидаем местоположение/);
    assert.equal(x.document.getElementById('mapRadius').textContent,'0.3');
    x.permission().resolve({coords:{latitude:41.3,longitude:69.2,accuracy:20}});await settle();
    assert.match(results.textContent,uz?/300 m.*izlayapmiz/:/Ищем организации.*300 м/);
    assert.equal(x.document.getElementById('listCount').textContent,uz?'Qidiruv…':'Поиск…');
    assert(!results.textContent.includes('не найдены'));
    google.resolve({places:[]});await settle();
    assert.equal(x.window.relyqoNearbyPending,false);
    assert.match(x.document.getElementById('currentPlaceMessage').textContent,uz?/hech narsa topilmadi/:/ничего не найдено/);
    assert(!results.textContent.includes('Ищем организации'));
  }
});
