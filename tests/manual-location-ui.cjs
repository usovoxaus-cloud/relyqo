const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const settle=async()=>{for(let i=0;i<10;i++)await new Promise(r=>setImmediate(r));};
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
async function setup(options={}) {
  const {window,document}=parseHTML(fs.readFileSync('app/static/nearby.html','utf8'));
  if(options.uz)document.documentElement.lang='uz';
  const changes=[],requests=[],maps=[],markers=[];let gps;
  window.HTMLElement.prototype.focus=function(){this.dataset.focused='true';};
  const google={maps:{Map:function(root,config){Object.assign(this,config);this.listeners={};this.addListener=(name,fn)=>this.listeners[name]=fn;this.setCenter=p=>this.center=p;this.setZoom=z=>this.zoom=z;maps.push(this);},Marker:function(config){Object.assign(this,config);this.listeners={};this.addListener=(name,fn)=>this.listeners[name]=fn;this.setPosition=p=>this.position=p;this.setMap=m=>this.map=m;markers.push(this);},importLibrary:async()=>({Place:{searchByText:async req=>{requests.push(req);return options.search?options.search(req):{places:[{formattedAddress:'Fixture address',location:{lat:()=>41.3,lng:()=>69.2}}]};}}})}};
  const context={document,window,google,setTimeout,clearTimeout,navigator:{geolocation:{getCurrentPosition(success,error,settings){gps={success,error,settings};}}}};
  vm.runInNewContext(fs.readFileSync('app/static/manual-location.js','utf8'),context);
  const picker=window.relyqoManualLocation({loadMaps:async()=>options.mapAvailable!==false,onChange:p=>changes.push(p?{...p}:null)});
  picker.reset();const $=id=>document.getElementById(id);const click=async id=>{$(id).click();await settle();};
  return{window,document,picker,$,click,changes,requests,maps,markers,gps:()=>gps};
}
test('optional location is idle until requested and GPS needs explicit confirmation',async()=>{
  const x=await setup();assert.equal(x.gps(),undefined);assert.equal(x.maps.length,0);assert(x.picker.validate());
  await x.click('manualUseGps');assert.equal(x.gps().settings.maximumAge,0);
  await x.gps().success({coords:{latitude:41.3,longitude:69.2,accuracy:20}});
  assert.equal(x.changes.at(-1),null);assert(!x.picker.validate());assert.equal(x.$('manualLocationConfirm').dataset.focused,'true');
  await x.click('manualLocationConfirm');assert.deepEqual(x.changes.at(-1),{lat:41.3,lng:69.2});assert(x.picker.validate());
  assert.equal(x.$('manualLocationConfirm').hidden,true);
});
test('imprecise and denied GPS remain optional without saving a point',async()=>{
  const x=await setup();await x.click('manualUseGps');await x.gps().success({coords:{latitude:41.3,longitude:69.2,accuracy:1200}});
  assert.match(x.$('manualLocationStatus').textContent,/GPS неточный/);assert.equal(x.changes.at(-1),null);assert(x.picker.validate());
  await x.click('manualUseGps');x.gps().error({code:1});assert.match(x.$('manualLocationStatus').textContent,/Геолокация недоступна/);assert(!x.$('manualUseGps').disabled);
});
test('map selection and dragging require fresh confirmation; changing address invalidates the point',async()=>{
  const x=await setup();await x.click('manualOpenMap');x.maps[0].listeners.click({latLng:{lat:()=>41.4,lng:()=>69.4}});
  assert(!x.picker.validate());await x.click('manualLocationConfirm');assert(x.picker.validate());
  x.markers[0].listeners.dragend({latLng:{lat:()=>41.5,lng:()=>69.5}});assert(!x.picker.validate());assert.equal(x.changes.at(-1),null);
  await x.click('manualLocationConfirm');assert.deepEqual(x.changes.at(-1),{lat:41.5,lng:69.5});
  x.$('manualAddress').dispatchEvent(new x.window.Event('input'));assert.equal(x.changes.at(-1),null);assert(x.picker.validate());assert.equal(x.markers[0].map,null);
});
test('closing or clearing during a GPS request ignores the late result',async()=>{
  const x=await setup();await x.click('manualUseGps');const old=x.gps();
  x.$('manualDialog').dispatchEvent(new x.window.Event('close'));await old.success({coords:{latitude:41.3,longitude:69.2,accuracy:10}});
  assert.equal(x.maps.length,0);assert(x.$('manualLocationConfirm').hidden);assert.equal(x.changes.at(-1),null);
});
test('address search requires city and address, offers a choice and never changes authored text',async()=>{
  const x=await setup();await x.click('manualFindAddress');assert.equal(x.requests.length,0);
  x.$('manualAddress').value='My street 12';x.$('manualCity').value='Tashkent';
  await x.click('manualFindAddress');assert.equal(x.requests.length,1);assert.equal(x.requests[0].language,'ru');
  x.document.querySelector('.manualAddressResult').click();await settle();
  assert.equal(x.$('manualAddress').value,'My street 12');assert(!x.picker.validate());
  await x.click('manualLocationConfirm');assert.deepEqual(x.changes.at(-1),{lat:41.3,lng:69.2});
});
test('an address edited while searching ignores old results',async()=>{
  const pending=deferred(),x=await setup({search:()=>pending.promise});x.$('manualAddress').value='Old street';x.$('manualCity').value='Tashkent';
  await x.click('manualFindAddress');x.$('manualAddress').dispatchEvent(new x.window.Event('input'));
  pending.resolve({places:[{formattedAddress:'Stale',location:{lat:()=>41,lng:()=>69}}]});await settle();
  assert.equal(x.document.querySelectorAll('.manualAddressResult').length,0);assert(!x.$('manualFindAddress').disabled);
});
test('GPS confirmation remains possible when map loading fails, with Uzbek copy',async()=>{
  const x=await setup({mapAvailable:false,uz:true});await x.click('manualUseGps');await x.gps().success({coords:{latitude:41.3,longitude:69.2,accuracy:10}});
  assert(!x.$('manualLocationPreview').hidden);assert.match(x.$('manualLocationStatus').textContent,/tasdiqlang/);
  await x.click('manualLocationConfirm');assert(x.picker.validate());assert.match(x.$('manualLocationStatus').textContent,/Nuqta tasdiqlandi/);
});
test('resetting an existing map retains the new draft and clearing never creates a default marker',async()=>{
  const x=await setup();await x.click('manualOpenMap');assert.equal(x.markers.length,0);
  x.picker.reset({location:{lat:40,lng:67}});assert(!x.picker.validate());await x.click('manualLocationConfirm');
  await x.click('manualOpenMap');assert(x.picker.validate());assert.deepEqual(x.changes.at(-1),{lat:40,lng:67});
  await x.click('manualLocationClear');assert.equal(x.changes.at(-1),null);assert(x.picker.validate());
});
