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
  document.getElementById('manualDialog').close=function(){this.open=false;};
  document.getElementById('manualForm').reset=function(){};
  document.getElementById('manualForm').reportValidity=function(){return !options.invalidManual;};
  const calls=[],markers=[],timers=new Map(),stored=new Map();let timer=0,map,gps=0,permission;
  if(options.saved)stored.set('relyqo.consumer.place.v1',JSON.stringify(options.saved));
  const google={maps:{Map:function(root,config){map=this;this.center={...config.center};this.setCenter=p=>{this.center={...p};};this.setZoom=z=>{this.zoom=z;};this.addListener=()=>{};this.getCenter=()=>({lat:()=>this.center.lat,lng:()=>this.center.lng});},Marker:function(config){Object.assign(this,config);this.listeners={};this.addListener=(event,fn)=>{this.listeners[event]=fn;};this.setMap=value=>{this.map=value;};this.setPosition=value=>{this.position=value;};markers.push(this);},importLibrary:async()=>({SearchNearbyRankPreference:{DISTANCE:'DISTANCE',POPULARITY:'POPULARITY'},Place:{searchNearby:async body=>{calls.push({nearby:body});return options.nearby?options.nearby(body):{places:[externalPlace(),externalPlace('foreign','KZ')]};},searchByText:async body=>{calls.push({text:body});return {places:[externalPlace()]};}}})}};
  const window={google:options.noGoogle?undefined:google,relyqoCategoriesReady:Promise.resolve([]),setTimeout:(fn,delay)=>{timers.set(++timer,{fn,delay});return timer;},clearTimeout:id=>timers.delete(id)};
  const context={document,window,google,Event:events.Event,MutationObserver:events.MutationObserver,URLSearchParams,Intl,AbortController,Map,Set,location:{search:options.search??'?find=search',pathname:options.pathname||'/rate',href:'/rate'},Option:function(text,value=text){const o=document.createElement('option');o.textContent=text;o.value=value;return o;},setTimeout:window.setTimeout,clearTimeout:window.clearTimeout,localStorage:{getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value)},navigator:{language:'ru',geolocation:{getCurrentPosition(resolve,reject,settings){gps++;permission={resolve,reject,settings};if(options.gps==='denied')reject({code:1});else if(options.gps!=='pending')resolve({coords:{latitude:41.3,longitude:69.2,accuracy:options.accuracy??20}});}}},fetch:async(url,settings={})=>{
    const body=settings.body?JSON.parse(settings.body):null;calls.push({url,body,method:settings.method||'GET'});
    if(url.startsWith('/v1/public/rated-organizations'))return reply({items:options.localPlaces||[localPlace],total:1,geography:[],facets:{countries:['UZ'],cities:[]}});
    if(url.startsWith('/static/uzbekistan.json'))return reply(locations);
    if(url==='/v1/public/app-content')return reply({content:{ru:{title:'Generic search title',hint:'Generic search hint'}}});
    if(url==='/v1/public/manual-places'&&options.manualFailure)return {ok:false,json:async()=>({detail:options.manualFailure})};
    if(url==='/v1/public/manual-places'&&options.confirmPlace)return reply({item:{...localPlace,id:'confirmed',...body}});
    if(url.endsWith('/nearby')&&options.localNearby)return options.localNearby(url,body);
    if(url==='/v1/public/manual-places/nearby')return reply({items:options.localPlaces||[localPlace]});
    if(url==='/v1/public/branches/nearby')return reply({items:[]});
    if(url==='/v1/public/maps-config')return reply({configured:false});
    if(url==='/v1/public/search/plan')return reply({ai_generated:false});
    throw Error('Unexpected request '+url);
  }};
  vm.createContext(context);
  for(const name of ['manual-location','nearby','ai-search','consumer-search','rate-discovery'])vm.runInContext(fs.readFileSync(`app/static/${name}.js`,'utf8'),context,{filename:name+'.js'});
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
  assert.equal(x.document.querySelector('.ratingQr').href,'/rate?find=qr');
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







test('late geolocation cannot replace a name search started while permission is pending',async()=>{
  const x=await harness({search:'?find=nearby',gps:'pending'});assert.equal(x.gps(),1);
  await x.type('Test');await x.runTimer(250);
  x.permission().resolve({coords:{latitude:42,longitude:60}});await settle();
  assert(!x.calls.some(c=>c.url?.endsWith('/nearby')));assert.equal(x.map(),undefined);
  assert.equal(x.document.getElementById('catalogQuery').value,'Test');assert(x.document.body.classList.contains('directoryMode'));
});



test('Uzbek entry and existing ordinary search remain distinct',async()=>{
  const x=await harness({search:'?find=search',uz:true});
  assert.equal(x.document.querySelector('.consumerTitle').textContent,'Qaysi tashkilotni baholaymiz?');
  assert.equal(x.document.getElementById('discoveryHere').textContent,'Yaqinimda');assert.equal(x.document.getElementById('discoveryByName').textContent,'Ro‘yxatdan');
  const normal=await harness({search:'?find=unsupported'});assert(!normal.document.body.classList.contains('ratingDiscovery'));
  assert.equal(normal.document.getElementById('discoveryMap'),null);assert.equal(normal.gps(),0);
});

const atVenue=(id,latitude=41.3001)=>({...localPlace,id,name:`Fixture ${id}`,latitude});
test('explicit nearby entry locates once using a fresh fix and a small search area',async()=>{
  const x=await harness({search:'?find=here',localPlaces:[atVenue('here',41.3)],nearby:()=>({places:[]})});
  assert.equal(x.gps(),1);assert.equal(x.permission().settings.maximumAge,0);
  assert.equal(x.permission().settings.enableHighAccuracy,true);
  for(const url of ['/v1/public/manual-places/nearby','/v1/public/branches/nearby'])assert.equal(x.calls.find(c=>c.url===url).body.radius_km,.3);
  assert.equal(x.calls.find(c=>c.nearby).nearby.locationRestriction.radius,300);
  assert.equal(x.document.getElementById('discoveryHere').getAttribute('aria-pressed'),'true');
  assert.equal(x.document.getElementById('currentPlaceMessage').textContent,'');
  const link=x.document.querySelector('#currentPlaceCandidates a');
  assert.equal(link.textContent,'Оценить');
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
  assert.match(y.document.getElementById('results').textContent,/ничего не найдено/);
});

test('poor GPS accuracy never claims to have identified the current organization',async()=>{
  const x=await harness({search:'?find=here',accuracy:2000,localPlaces:[atVenue('a')],nearby:()=>({places:[]})});
  assert.match(x.document.getElementById('currentPlaceMessage').textContent,/GPS неточный.*300 м.*Проверьте адрес/);
  assert.equal(x.document.getElementById('currentPlaceTitle').textContent,'Организации в радиусе 300 м');
  assert(x.calls.filter(c=>c.url?.endsWith('/nearby')).every(c=>c.body.radius_km===.3));
  assert(x.calls.filter(c=>c.nearby).every(c=>c.nearby.locationRestriction.radius===300));
  assert.equal(x.document.querySelectorAll('.currentPlaceCandidate').length,1);
});

test('denied current-location permission offers other methods and does not repeat the request',async()=>{
  const x=await harness({search:'?find=here',gps:'denied'});assert.equal(x.gps(),1);
  assert.match(x.document.getElementById('discoveryLocationNotice').textContent,/геолокации запрещён/);
  assert.equal(x.document.getElementById('discoveryHere').disabled,false);
  assert(x.document.getElementById('currentPlace').classList.contains('hidden'));
  await x.click('#discoveryByName');assert.equal(x.gps(),1);
  assert.equal(x.document.getElementById('discoveryByName').getAttribute('aria-pressed'),'true');assert.equal(x.gps(),1);
});

test('a pending current-location fix is discarded after switching to the list',async()=>{
  const x=await harness({search:'?find=here',gps:'pending'});
  await x.click('#discoveryByName');const before=x.calls.filter(c=>c.url?.endsWith('/nearby')).length;
  x.permission().resolve({coords:{latitude:42,longitude:60,accuracy:10}});await settle();
  assert.equal(x.calls.filter(c=>c.url?.endsWith('/nearby')).length,before);
  assert(x.document.getElementById('currentPlace').classList.contains('hidden'));
  assert(x.document.querySelector('#results .rateLink'));
});

test('late Google discovery updates current-place candidates without requiring a second GPS request',async()=>{
  let resolve;const pending=new Promise(r=>{resolve=r;});
  const x=await harness({search:'?find=here',localPlaces:[],nearby:()=>pending});
  assert.match(x.document.getElementById('results').textContent,/Ищем организации/);
  const place=externalPlace();place.location={lat:()=>41.3,lng:()=>69.2};
  resolve({places:[place]});await settle();
  assert.equal(x.gps(),1);assert.equal(x.document.querySelectorAll('.currentPlaceCandidate').length,1);
  await x.click('.currentPlaceCandidate button');assert(x.document.getElementById('manualDialog').open);
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'));
});

test('invalid geolocation never reaches the nearby endpoints',async()=>{
  const x=await harness({search:'?find=here',gps:'pending'});
  x.permission().resolve({coords:{latitude:NaN,longitude:69.2,accuracy:10}});await settle();
  assert(!x.calls.some(c=>c.url?.endsWith('/nearby')));
  assert.match(x.document.getElementById('discoveryLocationNotice').textContent,/Не удалось определить местоположение/);
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
  const x=await harness({search:'?find=here',localNearby:url=>url.includes('/branches/')?branches.promise:manual.promise,nearby:()=>google.promise});
  assert(x.map());assert.equal(x.document.getElementById('map').classList.contains('hidden'),false);
  assert.match(x.document.getElementById('status').textContent,/300 м/);
  google.resolve({places:[googleAt(200)]});await settle();
  assert.deepEqual(names(x),['Google 200']);assert.equal(x.gps(),1);
  assert.equal(x.document.getElementById('discoveryHere').disabled,false);
  manual.resolve(reply({items:[localAt(100)]}));await settle();assert.deepEqual(names(x),['Local 100','Google 200']);
  branches.reject(Error('local unavailable'));await settle();assert.deepEqual(names(x),['Local 100','Google 200']);
  assert.equal(x.window.relyqoNearbyPending,false);assert.match(x.document.getElementById('error').textContent,/Часть организаций не загрузилась/);
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'));
});

test('local failures before Google resolves do not invalidate successful Places results',async()=>{
  const google=deferred();
  const x=await harness({search:'?find=here',localNearby:()=>{throw Error('local offline');},nearby:()=>google.promise});
  assert.equal(x.window.relyqoNearbyState.localFailed,2);
  google.resolve({places:[googleAt(280)]});await settle();
  assert.deepEqual(names(x),['Google 280']);assert.equal(x.gps(),1);
  await x.click('.currentPlaceSelect');assert(x.document.getElementById('manualDialog').open);
  assert.equal(x.document.getElementById('manualName').value,'Google 280');
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'));
});

test('Google failure keeps local places 150–300m visible with an honest partial-result message',async()=>{
  const x=await harness({search:'?find=here',localPlaces:[localAt(280)],nearby:()=>{throw Error('Google offline');}});
  assert.deepEqual(names(x),['Local 280']);assert.match(x.document.getElementById('error').textContent,/Часть организаций не загрузилась/);
  assert.equal(x.window.relyqoNearbyPending,false);assert.equal(x.gps(),1);
});

test('late local and Google replies from an old fix cannot replace a newer search',async()=>{
  const local=deferred(),google=deferred();let fresh=false;
  const x=await harness({search:'?find=here',localNearby:url=>fresh?reply({items:url.includes('/manual-places/')?[localAt(80)]:[]}):local.promise,nearby:()=>fresh?{places:[googleAt(90)]}:google.promise});
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
  await x.click('#discoveryByName');assert.equal(radius.value,'8');assert.equal(limit.value,'50');assert.equal(radius.disabled,false);
  assert.equal(x.document.getElementById('currentRadiusControl').hidden,true);
  await x.click('#discoveryHere');assertScope(x,750);
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
  const x=await harness({search:'?find=here',localPlaces:local,nearby:()=>({places:google})});
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
  const x=await harness({search:'?find=here',localPlaces:[localAt(749.99),localAt(750),localAt(750.01)],nearby:()=>({places:[googleAt(600),googleAt(750),googleAt(750.01)]})});
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
  const x=await harness({search:'?find=here'}),original=names(x),count=x.calls.length,gps=x.gps();
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
  const x=await harness({search:'?find=here',gps:'pending'});
  await x.click('[data-radius="1000"]');await editRadius(x,'750');
  assert.equal(nearbyCalls(x).length,0);assert.equal(x.gps(),1);
  assert.equal(x.document.getElementById('currentRadiusMeters').disabled,false);
  assert.match(x.document.getElementById('currentRadiusSummary').textContent,/750 м/);
  assert.match(x.document.getElementById('results').textContent,/750 м/);
  x.permission().resolve({coords:{latitude:41.3,longitude:69.2,accuracy:20}});await settle();
  assertScope(x,750);assert.equal(nearbyCalls(x).length,2);assert.equal(x.gps(),1);
});

test('invalid draft during pending GPS prevents the initial search until corrected without another GPS prompt',async()=>{
  const x=await harness({search:'?find=here',gps:'pending'});await editRadius(x,'50001',false);
  x.permission().resolve({coords:{latitude:41.3,longitude:69.2,accuracy:20}});await settle();
  assert.equal(nearbyCalls(x).length,0);assert(!x.calls.some(c=>c.nearby));
  assert(!x.document.getElementById('results').textContent.includes('ничего не найдено'));
  await editRadius(x,'750');assertScope(x,750);assert.equal(x.gps(),1);
});

test('settings survive denied GPS without an automatic permission retry and fresh retry retains the chosen radius',async()=>{
  const x=await harness({search:'?find=here',gps:'pending'});await x.click('[data-radius="1000"]');
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
  const x=await harness({search:'?find=here',localNearby:(url,body)=>body.radius_km===1?wideLocal.promise:reply({items:url.includes('/manual-places/')?[localAt(150)]:[]}),nearby:body=>body.locationRestriction.radius===1000?wideGoogle.promise:{places:[googleAt(200)]}});
  await x.click('[data-radius="1000"]');await x.click('[data-radius="300"]');
  assert.deepEqual(names(x),['Local 150','Google 200']);
  wideLocal.resolve(reply({items:[localAt(850)]}));wideGoogle.resolve({places:[googleAt(900)]});await settle();
  assert.deepEqual(names(x),['Local 150','Google 200']);assertScope(x,300);assert.equal(x.gps(),1);
});

test('dynamic RU/UZ loading, empty, error and low-accuracy text use the chosen radius',async()=>{
  for(const uz of [false,true]){
    const answer=deferred();let failing=false;
    const x=await harness({search:'?find=here',uz,accuracy:2000,localPlaces:[],nearby:()=>failing?Promise.reject(Error('offline')):answer.promise});
    await x.click('[data-radius="1000"]');
    const unit=uz?'1 km':'1 км';
    for(const id of ['currentPlaceTitle','currentPlaceMessage','results','status','scopeHint'])assert(x.document.getElementById(id).textContent.includes(unit),id);
    assert.match(x.document.getElementById('currentPlaceMessage').textContent,uz?/GPS noaniq/:/GPS неточный/);
    answer.resolve({places:[]});await settle();
    assert(x.document.getElementById('results').textContent.includes(unit));
    assert.match(x.document.getElementById('results').textContent,uz?/hech narsa topilmadi/:/ничего не найдено/);
    failing=true;await editRadius(x,'750');
    for(const id of ['currentPlaceTitle','currentPlaceMessage','results','currentRadiusSummary'])assert(x.document.getElementById(id).textContent.includes(uz?'750 m':'750 м'),id);
  }
});

test('minimum and maximum custom radii are sent without Google clamping or extra search zones',async()=>{
  const x=await harness({search:'?find=here'});
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
  await x.click('#discoveryByName');
  assert(!x.document.body.classList.contains('findingCurrentPlace'));
  assert.equal(x.document.getElementById('mapRadius').textContent,'8');
  assert.match(x.document.getElementById('scopeHint').textContent,/8 км/);
  x.permission().reject({code:1});await settle();
  assert.equal(x.document.getElementById('mapRadius').textContent,'8');assert.equal(x.gps(),1);
  local.resolve(reply({items:[]}));google.resolve({places:[]});await settle();
});

test('denied GPS restores ordinary labels when leaving current-place mode without repeating permission',async()=>{
  const x=await harness({search:'?find=here',gps:'pending'});
  assert.equal(x.document.getElementById('mapRadius').textContent,'0.3');
  x.permission().reject({code:1});await settle();
  assert(!x.document.body.classList.contains('findingCurrentPlace'));
  assert(x.document.getElementById('currentPlace').classList.contains('hidden'));
  assert.equal(x.document.getElementById('mapRadius').textContent,'15');
  assert.match(x.document.getElementById('scopeHint').textContent,/15 км/);
  assert.match(x.document.getElementById('discoveryLocationNotice').textContent,/геолокации запрещён/);
  assert(!x.document.getElementById('results').textContent.includes('Ожидаем местоположение'));
  assert(x.document.querySelector('#place-manual-fixture-local .rateLink'));
  assert.equal(x.gps(),1);assert(!x.calls.some(c=>c.url?.endsWith('/nearby')));
});

test('current-place list waits for GPS and outstanding sources in RU/UZ, then shows a completed empty result',async()=>{
  for(const uz of [false,true]){
    const google=deferred();
    const x=await harness({search:'?find=here',gps:'pending',uz,localPlaces:[],nearby:()=>google.promise});
    const results=x.document.getElementById('results');
    assert.match(results.textContent,uz?/joylashuvni kutyapmiz/:/Ожидаем местоположение/);
    assert.equal(x.document.getElementById('mapRadius').textContent,'0.3');
    x.permission().resolve({coords:{latitude:41.3,longitude:69.2,accuracy:20}});await settle();
    assert.match(results.textContent,uz?/300 m.*izlayapmiz/:/Ищем организации.*300 м/);
    assert.equal(x.document.getElementById('listCount').textContent,uz?'Qidiruv…':'Поиск…');
    assert(!results.textContent.includes('не найдены'));
    google.resolve({places:[]});await settle();
    assert.equal(x.window.relyqoNearbyPending,false);
    assert.match(x.document.getElementById('results').textContent,uz?/hech narsa topilmadi/:/ничего не найдено/);
    assert(!results.textContent.includes('Ищем организации'));
  }
});

async function openRatingForm(href) {
  const url=new URL(href,'https://example.test');assert.equal(url.pathname,'/community-rate');
  const {document,window}=parseHTML(fs.readFileSync('app/static/community-rate.html','utf8'));
  window.relyqoCategoryGroup=()=>undefined;window.relyqoCategoriesReady=Promise.resolve([]);window.relyqoFeedback=()=>({});window.relyqoRatingPhoto=()=>({value:()=>null});window.scrollTo=()=>{};
  const calls=[],context={document,window,URLSearchParams,location:{pathname:url.pathname,search:url.search},fetch:async url=>{calls.push(url);return reply({role:'CONSUMER'});}};
  vm.runInNewContext([...document.querySelectorAll('script:not([src])')].map(s=>s.textContent).join('\n'),context);await settle();
  assert.equal(document.getElementById('placeName').textContent,url.searchParams.get('name'));
  assert.equal(document.getElementById('placeAddress').textContent,url.searchParams.get('address'));
  assert.equal(document.querySelectorAll('#metrics select').length,5);
  assert([...document.querySelectorAll('#metrics select')].every(input=>input.value===''));
  assert(!calls.some(url=>url.includes('ratings')));return document;
}

test('ordinary consumer and rate entry show one list and two primary modes, without GPS or expanded settings',async()=>{
  for(const pathname of ['/consumer','/rate'])for(const uz of [false,true]){
    const x=await harness({pathname,search:'',uz,saved:{region:'10',city:'Samarkand'}});
    assert.equal(x.gps(),0);assert(!x.calls.some(c=>c.nearby||c.url?.endsWith('/nearby')));
    assert.equal(x.document.getElementById('ratedRegion').value,'ALL');assert.equal(x.document.getElementById('ratedCity').value,'ALL');
    assert.deepEqual([...x.document.querySelectorAll('.ratingDiscoveryActions button')].map(e=>e.textContent),uz?['Yaqinimda','Ro‘yxatdan']:['Рядом со мной','По списку']);
    assert.equal(x.document.getElementById('discoveryByName').getAttribute('aria-pressed'),'true');
    assert(x.document.getElementById('currentRadiusControl').hidden);assert(!x.document.getElementById('currentRadiusControl').open);
    for(const selector of ['.consumerChips','.consumerPlace','.catalogOptions','.searchAdvanced','.advisorDetails','#mapCard','#locate','#status'])assert(x.document.querySelector(selector).hidden,selector);
    assert.equal(x.document.querySelectorAll('#results .place').length,1);
    assert.equal(x.document.querySelectorAll('#results .rateLink').length,1);
    assert.equal(x.document.querySelector('#results .rateLink').textContent,uz?'Baholash':'Оценить');
    assert.equal(x.document.querySelectorAll('#results button,#results a').length,1);
    assert(!x.document.querySelector('#results small')); // No invented distance without coordinates.
    assert.equal(x.document.querySelector('.ratingQr').href,'/rate?find=qr');
    await openRatingForm(x.document.querySelector('#results .rateLink').getAttribute('href'));
  }
});

test('list search reaches the existing partner rating form with the correct source and no GPS',async()=>{
  const partner={...localPlace,kind:'partner',id:'partner-one',branch_id:'partner-one',name:'Fregat',organization:'Fregat',branch:'Main'};
  const x=await harness({pathname:'/consumer',search:'',localPlaces:[partner]});
  await x.type('Fregat');await x.runTimer(250);
  const link=x.document.querySelector('#results .rateLink');assert(link);
  const url=new URL(link.getAttribute('href'),'https://example.test');assert.equal(url.searchParams.get('source'),'RELYQO_PARTNER');assert.equal(url.searchParams.get('object_key'),'relyqo:partner-one');
  await openRatingForm(link.getAttribute('href'));assert.equal(x.gps(),0);
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'||c.url?.includes('/ratings')));
});

test('nearby button loads a single actionable list and external confirmation reaches the existing rating form',async()=>{
  const x=await harness({search:'',confirmPlace:true});assert.equal(x.gps(),0);
  await x.click('#discoveryHere');assertScope(x,300);assert.equal(x.gps(),1);
  assert.equal(x.document.getElementById('currentRadiusControl').hidden,false);assert(!x.document.getElementById('currentRadiusControl').open);
  assert.equal(x.document.getElementById('currentRadiusSummary').textContent,'Расстояние: 300 м');
  assert.equal(x.document.querySelectorAll('#results .place').length,2);
  assert.equal(x.document.querySelectorAll('.currentPlaceCandidate').length,2); // No duplicate selection panel.
  assert.equal(x.document.querySelectorAll('#results .rateLink').length,2);
  await openRatingForm(x.document.querySelector('#place-manual-fixture-local .rateLink').getAttribute('href'));
  await x.click('#place-external-fixture-google .rateLink');assert(x.document.getElementById('manualDialog').open);
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'));
  await x.click('#manualLocationConfirm');
  const event=new x.events.Event('submit',{cancelable:true});event.submitter=x.document.querySelector('#manualForm [type=submit]');
  x.document.getElementById('manualForm').dispatchEvent(event);await settle();
  assert.equal(x.calls.filter(c=>c.url==='/v1/public/manual-places').length,1);
  const url=new URL(x.context.location.href,'https://example.test');assert.equal(url.searchParams.get('object_key'),'manual:confirmed');
  await openRatingForm(x.context.location.href);assert.equal(x.gps(),1);
});

test('exhausted or denied location shows a scoped RU/UZ notice and restores a working list',async()=>{
  for(const uz of [false,true])for(const code of [1,2,3]){
    const x=await harness({search:'',gps:'pending',uz});await x.click('#discoveryHere');
    x.permission().reject({code,message:'Timeout expired / raw provider error'});await settle();
    if(code!==1){
      assert.equal(x.gps(),2);assert(x.document.body.classList.contains('findingCurrentPlace'));
      assert(x.document.getElementById('discoveryLocationNotice').hidden);
      x.permission().reject({code,message:'Timeout expired / raw provider error'});await settle();
    }
    const notice=x.document.getElementById('discoveryLocationNotice'),error=notice.textContent;
    assert.equal(notice.hidden,false);assert.equal(notice.getAttribute('role'),'status');
    assert(x.document.getElementById('error').classList.contains('hidden'));
    assert.match(error,uz?/ro‘yxatdan tanlang/:/из списка/);assert.doesNotMatch(error,/Timeout|expired|provider/);
    assert(x.document.querySelector('#results .rateLink'));assert(!x.document.body.classList.contains('findingCurrentPlace'));
    assert.equal(x.document.getElementById('discoveryByName').getAttribute('aria-pressed'),'true');
    assert(x.document.getElementById('currentRadiusControl').hidden);
    await openRatingForm(x.document.querySelector('#results .rateLink').getAttribute('href'));
    await x.click('#discoveryByName');assert.equal(x.gps(),code===1?1:2);assert(notice.hidden);assert.equal(notice.textContent,'');
  }
});

test('a timeout or unavailable high-accuracy fix retries once and searches with the actual fallback coordinates',async()=>{
  for(const code of [2,3])for(const uz of [false,true]){
    const x=await harness({search:'?find=here',gps:'pending',uz});
    x.permission().reject({code});await settle();
    assert.equal(x.gps(),2);assert.equal(x.permission().settings.enableHighAccuracy,false);
    assert.equal(x.permission().settings.timeout,8000);assert.equal(x.permission().settings.maximumAge,0);
    assert.equal(nearbyCalls(x).length,0);assert(x.document.getElementById('discoveryHere').disabled);
    assert.match(x.document.getElementById('results').textContent,uz?/joylashuvni kutyapmiz/:/Ожидаем местоположение/);
    assert(x.document.getElementById('error').classList.contains('hidden'));
    await x.click('[data-radius="1000"]');
    x.permission().resolve({coords:{latitude:41.302,longitude:69.201,accuracy:700}});await settle();
    assert.equal(x.gps(),2);assertScope(x,1000);
    assert(nearbyCalls(x).every(c=>c.body.latitude===41.302&&c.body.longitude===69.201));
    assert.match(x.document.getElementById('currentPlaceMessage').textContent,uz?/GPS noaniq/:/GPS неточный/);
    assert(x.document.getElementById('discoveryLocationNotice').hidden);
    assert.equal(x.document.getElementById('discoveryHere').disabled,false);
  }
});

test('leaving either GPS attempt cancels retries and late results cannot replace the typed list',async()=>{
  for(const phase of [1,2])for(const outcome of ['resolve','reject']){
    const x=await harness({search:'?find=here',gps:'pending'});
    if(phase===2){x.permission().reject({code:3});await settle();}
    const pending=x.permission();await x.type('Test');await x.runTimer(250);
    assert.equal(x.document.getElementById('discoveryHere').disabled,false);
    pending[outcome](outcome==='resolve'?{coords:{latitude:41.3,longitude:69.2,accuracy:20}}:{code:3});await settle();
    assert.equal(x.gps(),phase);assert.equal(nearbyCalls(x).length,0);
    assert.equal(x.document.getElementById('catalogQuery').value,'Test');
    assert.equal(x.document.getElementById('discoveryByName').getAttribute('aria-pressed'),'true');
    assert(x.document.getElementById('discoveryLocationNotice').hidden);
    assert(x.document.getElementById('error').classList.contains('hidden'));
  }
});

test('starting a list search or a fresh nearby attempt clears the previous location notice immediately',async()=>{
  for(const action of ['type','search','nearby']){
    const x=await harness({search:'?find=here',gps:'pending'});
    x.permission().reject({code:1});await settle();
    const notice=x.document.getElementById('discoveryLocationNotice');assert(!notice.hidden);
    if(action==='type')await x.type('Test');
    else await x.click(action==='search'?'#catalogSearchButton':'#discoveryHere');
    assert(notice.hidden);assert.equal(notice.textContent,'');
    assert.equal(x.gps(),action==='nearby'?2:1);
  }
});

test('a cancelled GPS callback cannot enable the button for a newer pending nearby attempt',async()=>{
  const x=await harness({search:'?find=here',gps:'pending'}),old=x.permission();
  await x.click('#discoveryByName');await x.click('#discoveryHere');
  old.reject({code:3});await settle();
  assert.equal(x.gps(),2);assert(x.document.getElementById('discoveryHere').disabled);
  x.permission().resolve({coords:{latitude:41.3,longitude:69.2,accuracy:20}});await settle();
  assert.equal(x.document.getElementById('discoveryHere').disabled,false);assertScope(x,300);
});

test('a catalog loading error after GPS failure remains visible alongside the location notice',async()=>{
  const x=await harness({search:'?find=here',gps:'pending'}),original=x.context.fetch;
  x.context.fetch=(url,options)=>url.startsWith('/v1/public/rated-organizations')?Promise.reject(Error('catalog unavailable')):original(url,options);
  x.permission().reject({code:1});await settle();
  assert(!x.document.getElementById('error').classList.contains('hidden'));
  assert.match(x.document.getElementById('error').textContent,/catalog unavailable/);
  assert.match(x.document.getElementById('discoveryLocationNotice').textContent,/геолокации запрещён/);
});

test('separate advanced nearby catalog retains its controls and does not receive the simple rating renderer',async()=>{
  const x=await harness({pathname:'/nearby',search:''});
  assert(!x.document.body.classList.contains('ratingDiscovery'));assert.equal(x.window.relyqoRenderRatingRows,undefined);
  assert.equal(x.document.getElementById('discoveryHere'),null);assert(!x.document.getElementById('locate').hidden);
  assert(x.document.querySelector('#results .rateLink'));assert.equal(x.gps(),0);
});


test('Find while permission is pending switches to the list without a second GPS request',async()=>{
  const x=await harness({search:'',gps:'pending'});await x.click('#discoveryHere');assert.equal(x.gps(),1);
  await x.click('#catalogSearchButton');assert.equal(x.gps(),1);assert(!x.document.body.classList.contains('findingCurrentPlace'));
  x.permission().resolve({coords:{latitude:41.3,longitude:69.2,accuracy:20}});await settle();
  assert(!x.calls.some(c=>c.url?.endsWith('/nearby')));assert(x.document.querySelector('#results .rateLink'));
});

test('missing-place action is available after results, empty searches and denied GPS in both languages',async()=>{
  for(const pathname of ['/consumer','/rate'])for(const uz of [false,true])for(const scenario of ['results','empty','nearby-empty','denied']){
    const x=await harness({pathname,search:scenario==='denied'||scenario==='nearby-empty'?'?find=here':'',uz,
      gps:scenario==='denied'?'denied':undefined,localPlaces:scenario==='empty'||scenario==='nearby-empty'?[]:undefined,nearby:()=>({places:[]})});
    const add=x.document.getElementById('addPlace');
    assert(!add.hidden);assert(!add.disabled);
    assert.equal(x.document.getElementById('listCard').nextElementSibling,add);
    assert.equal(add.textContent,uz?'Tashkilotni topmadingizmi? Tashkilot qo‘shish':'Не нашли организацию? Добавить организацию');
    const gps=x.gps();await x.click('#addPlace');
    assert(x.document.getElementById('manualDialog').open);assert.equal(x.gps(),gps);
    assert.equal(x.document.querySelector('#manualForm [type=submit]').textContent,uz?'Qo‘shish va baholash':'Добавить и оценить');
    await x.click('#cancelManual');assert(!x.document.getElementById('manualDialog').open);
    assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'||c.url?.includes('/ratings')));
  }
});

test('add action preserves the editable search name without inventing an address or carrying over another place',async()=>{
  const x=await harness({search:'?find=here'});
  await x.click('#place-external-fixture-google .rateLink');await x.click('#cancelManual');
  await x.type('  New cafe & bakery  ');
  await x.click('#addPlace');
  assert.equal(x.document.getElementById('manualName').value,'New cafe & bakery');
  assert.equal(x.document.getElementById('manualAddress').value,'');
  assert.equal(x.document.getElementById('manualCity').value,'');
  assert.equal(x.document.getElementById('manualDescription').value,'');
  assert.equal(x.document.getElementById('manualCategory').value,'OTHER');
  assert(!x.calls.some(c=>c.url==='/v1/public/manual-places'));
});

test('confirmed missing-place creation reaches its own rating form without visitor coordinates or a rating submission',async()=>{
  const x=await harness({search:'?find=here',confirmPlace:true});
  await x.type('New cafe');await x.click('#addPlace');
  for(const [id,value] of Object.entries({manualName:'New cafe edited',manualDescription:'A real cafe entered by its visitor.',manualAddress:'Example street 12',manualCity:'Samarkand',manualCountry:'UZ'}))x.document.getElementById(id).value=value;
  const event=new x.events.Event('submit',{cancelable:true}); // Enter may have no submitter.
  x.document.getElementById('manualForm').dispatchEvent(event);await settle();
  const writes=x.calls.filter(c=>c.url==='/v1/public/manual-places');assert.equal(writes.length,1);
  assert.equal(writes[0].body.name,'New cafe edited');assert.equal(writes[0].body.city,'Samarkand');
  assert.equal(writes[0].body.latitude,null);assert.equal(writes[0].body.longitude,null);assert.equal(writes[0].body.google_place_id,null);
  assert(!x.document.getElementById('manualDialog').open);
  const url=new URL(x.context.location.href,'https://example.test');assert.equal(url.searchParams.get('object_key'),'manual:confirmed');assert.equal(url.searchParams.get('name'),'New cafe edited');
  await openRatingForm(x.context.location.href);
  assert(!x.calls.some(c=>c.url?.includes('/ratings')));
});

test('invalid forms never write and rejected additions retain user input for correction',async()=>{
  const invalid=await harness({search:'',invalidManual:true});await invalid.click('#addPlace');
  invalid.document.getElementById('manualForm').dispatchEvent(new invalid.events.Event('submit',{cancelable:true}));await settle();
  assert(invalid.document.getElementById('manualDialog').open);assert(!invalid.calls.some(c=>c.url==='/v1/public/manual-places'));
  const x=await harness({search:'?find=search&q=My%20place',manualFailure:'Check the address'});await x.click('#addPlace');
  x.document.getElementById('manualForm').dispatchEvent(new x.events.Event('submit',{cancelable:true}));await settle();
  assert(x.document.getElementById('manualDialog').open);assert.equal(x.document.getElementById('manualName').value,'My place');
  assert.equal(x.document.getElementById('manualError').textContent,'Check the address');assert(!x.document.querySelector('#manualForm [type=submit]').disabled);
  assert.equal(x.context.location.href,'/rate');assert(!x.calls.some(c=>c.url?.includes('/ratings')));
});
