const {test}=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const {parseHTML}=require('linkedom');
const read=file=>fs.readFileSync('app/static/'+file,'utf8');
const settle=async()=>{for(let i=0;i<6;i++)await new Promise(r=>setImmediate(r));};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
// Fixture values only: these are not reviews of a real establishment.
const example=()=>({id:'test-place',displayName:'Example Cafe',formattedAddress:'Test Street 12, Tashkent',rating:4.6,userRatingCount:128,googleMapsURI:'https://maps.google.com/?cid=123',attributions:[],addressComponents:[
 {types:['country'],shortText:'UZ',longText:'Uzbekistan'}, {types:['locality'],longText:'Tashkent'},
 {types:['route'],longText:'Test Street'}, {types:['street_number'],longText:'12'}]});
function harness(){
 const {document,window}=parseHTML('<html lang="ru"><body><section id="google"></section><input id="quality" value=""><strong id="community">80/100</strong></body></html>');
 const calls=[], state={places:[example()],details:example()}, root=document.getElementById('google');
 class Place {
  constructor(options){calls.push({constructor:options});}
  async fetchFields(request){calls.push({fields:request.fields});if(state.failure)throw Error('API unavailable');Object.assign(this, state.details);}
  static async searchByText(request){calls.push({search:request});return {places:state.places};}
 }
 window.google={maps:{importLibrary:async()=>({Place})}};
 const context={document,window,URL,URLSearchParams,AbortController,setTimeout,clearTimeout,localStorage:{setItem(){throw Error('No persistent Google cache allowed');}},fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({google_reference:{google_place_id:'canonical-place'}})};}};
 vm.runInNewContext(read('google-rating.js'),context);
 return {document,window,root,calls,state,Place,context,api:window.relyqoGoogleRating};
}
test('real Google fields display on the five-point scale with count and attribution, without filling personal scores',async()=>{
 const x=harness();x.state.details.attributions=[{provider:'Provider <img>',providerURI:'https://example.com/provider'}];
 await x.api.mount(x.root,{google_place_id:'canonical-place'});
 assert.match(x.root.textContent,/4\.6\/5/);assert.match(x.root.textContent,/128 оценок/);
 assert.equal(x.root.querySelector('.googleRatingBrand').getAttribute('translate'),'no');
 assert(x.root.querySelector('a[href="https://maps.google.com/?cid=123"]'));
 assert.equal(x.root.querySelector('img'),null);assert.match(x.root.textContent,/Provider <img>/);
 assert.equal(x.document.getElementById('quality').value,'');assert.equal(x.document.getElementById('community').textContent,'80/100');
 assert(x.calls.find(c=>c.fields).fields.includes('userRatingCount'));assert(!x.calls.find(c=>c.fields).fields.includes('*'));
});
test('missing or invalid Google numbers stay unavailable, never become zero or default sevens',()=>{
 const x=harness();for(const rating of [undefined,null,NaN,Infinity,0,7,'4.8']){
  x.api.render(x.root,{...example(),rating,userRatingCount:0,googleMapsURI:'javascript:alert(1)'});
  assert.match(x.root.textContent,/Нет оценки Google/);assert.doesNotMatch(x.root.textContent,/0\.0\/5|7\/10/);assert.equal(x.root.querySelector('a'),null);
 }
 x.api.render(x.root,{...example(),userRatingCount:undefined});assert.match(x.root.textContent,/Число оценок недоступно/);
});
test('automatic Google matching requires the same name, city and street number; ambiguous matches stay unlinked',async()=>{
 const x=harness(),reference={name:'Example Cafe',address:'Tashkent, Test Street 12',city:'Toshkent',country_code:'UZ',latitude:null,longitude:null};
 await x.api.mount(x.root,reference);assert.match(x.root.textContent,/4\.6\/5/);
 x.state.places=[{...example(),id:'wrong-name',displayName:'Other Cafe'}];await x.api.mount(x.root,reference);assert.match(x.root.textContent,/совпадение.*не найдено/);
 x.state.places=[example()];await x.api.mount(x.root,{...reference,address:'Tashkent, Test Street 120'});assert.doesNotMatch(x.root.textContent,/4\.6\/5/);
 await x.api.mount(x.root,{...reference,city:'Samarkand'});assert.doesNotMatch(x.root.textContent,/4\.6\/5/);
 x.state.places=[example(),{...example(),id:'another-branch',rating:5}];await x.api.mount(x.root,reference);assert.doesNotMatch(x.root.textContent,/\/5/);
});
test('Google timeout or denial does not prevent personal scoring and can be retried',async()=>{
 const x=harness();x.state.failure=true;await x.api.mount(x.root,{google_place_id:'test-place'});
 assert.match(x.root.textContent,/временно недоступен/);assert.equal(x.document.getElementById('quality').disabled,false);
 x.state.failure=false;x.root.querySelector('button').click();await settle();assert.match(x.root.textContent,/4\.6\/5/);
});
test('late Google requests cannot replace a newly selected organization',async()=>{
 const x=harness(),slow=deferred();x.Place.prototype.fetchFields=async function(){await slow.promise;Object.assign(this,example());};
 const old=x.api.mount(x.root,{google_place_id:'old'});await settle();
 x.Place.prototype.fetchFields=async function(){Object.assign(this,{...example(),rating:3.2});};
 await x.api.mount(x.root,{google_place_id:'new'});slow.resolve();await old;assert.match(x.root.textContent,/3\.2\/5/);assert.doesNotMatch(x.root.textContent,/4\.6\/5/);
});
test('rating forms resolve Google identity from the canonical server profile and localize to Uzbek',async()=>{
 const x=harness();x.document.documentElement.lang='uz';await x.api.forObject(x.root,'manual:real');
 assert.equal(x.calls[0].url,'/v1/public/place?object_key=manual%3Areal');
 assert.equal(x.calls.find(c=>Object.hasOwn(c,'constructor')).constructor.id,'canonical-place');
 assert.match(x.root.textContent,/128 ta baho/);assert.match(x.root.textContent,/Google Maps/);
});
test('a late canonical profile cannot replace the Google rating for the current organization',async()=>{
 const x=harness(),slow=deferred();
 x.context.fetch=async url=>{
  if(url.includes('manual%3Aold'))await slow.promise;
  return {ok:true,json:async()=>({google_reference:{google_place_id:url.includes('manual%3Aold')?'old':'new'}})};
 };
 const old=x.api.forObject(x.root,'manual:old');await settle();
 await x.api.forObject(x.root,'manual:new');slow.resolve();await old;
 assert.deepEqual(x.calls.filter(c=>Object.hasOwn(c,'constructor')).map(c=>c.constructor.id),['new']);
 assert.match(x.root.textContent,/4\.6\/5/);
});
