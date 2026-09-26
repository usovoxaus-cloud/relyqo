const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const script=vm.runInNewContext(fs.readFileSync('mobile/src/consumer.ts','utf8').replace('export const CONSUMER_PRESENTATION =','globalThis.consumerSource =')+';consumerSource');
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));};
async function harness(saved=null,uz=false){
 const {document,window}=parseHTML(fs.readFileSync('app/static/nearby.html','utf8'));if(uz)document.documentElement.lang='uz';
 Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.hasAttribute('selected'))?.value||this.options[0]?.value||''},set(v){for(const o of this.options)o.removeAttribute('selected');[...this.options].find(o=>o.value===v)?.setAttribute('selected','')}});
 const stored=new Map(saved?[['relyqo.consumer.place.v1',JSON.stringify(saved)]]:[]);
 const data=JSON.parse(fs.readFileSync('app/static/uzbekistan.json','utf8'));window.relyqoUzbekistan=data;
 const region=document.getElementById('ratedRegion'),city=document.getElementById('ratedCity');
 function cities(){city.replaceChildren();for(const row of [{city:'ALL',label_ru:'Вся область'},...data.cities.filter(x=>x.region_code===region.value)]){const o=document.createElement('option');o.value=row.city;o.textContent=row.label_ru;city.append(o);}city.value='ALL';}
 region.addEventListener('change',cities);
 const context={document,window,Event:window.Event,MutationObserver:window.MutationObserver,Array,JSON,String,AbortController,setTimeout,clearTimeout,localStorage:{getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value)},fetch:async()=>({ok:false})};
 vm.runInNewContext(script,context);await settle();return{document,window,context,stored};
}
test('search is first, filters collapsed, categories dispatch changes and duplicate injection is harmless',async()=>{
 const x=await harness(),d=x.document;assert.equal(d.querySelector('.consumerTitle').textContent,'Что вы ищете?');assert(!d.querySelector('.consumerPlace').hasAttribute('open'));
 assert(d.querySelector('.consumerPlace #ratedCity'));assert(d.querySelector('.catalogSearchWrap'));assert.equal(d.querySelectorAll('.consumerChips button').length,6);
 d.querySelector('[data-category="HEALTH"]').click();assert.equal(d.getElementById('ratedCategory').value,'HEALTH');assert.equal(d.querySelector('[data-category="HEALTH"]').getAttribute('aria-pressed'),'true');
 vm.runInNewContext(script,x.context);assert.equal(d.querySelectorAll('.consumerTitle').length,1);
 const ad=d.createElement('aside');ad.className='relyqo-ad-top';d.body.prepend(ad);await settle();assert.equal(ad.parentElement.tagName,'MAIN');
});
test('valid saved city is restored without storing any account data',async()=>{
 const x=await harness({region:'10',city:'Samarkand'}),d=x.document;assert.equal(d.getElementById('ratedRegion').value,'10');assert.equal(d.getElementById('ratedCity').value,'Samarkand');assert.match(d.querySelector('.consumerPlace summary').textContent,/Самарканд/);
 d.getElementById('ratedRegion').value='13';d.getElementById('ratedRegion').dispatchEvent(new x.window.Event('change',{bubbles:true}));await settle();assert.deepEqual(JSON.parse(x.stored.get('relyqo.consumer.place.v1')),{region:'13',city:'ALL'});
});
test('unknown saved locations fall back safely and Uzbek interface is available',async()=>{
 const x=await harness({region:'invalid',city:'invented'},true);assert.equal(x.document.getElementById('ratedRegion').value,'ALL');assert.equal(x.document.querySelector('.consumerTitle').textContent,'Nima izlayapsiz?');
 assert.match(x.document.getElementById('consumer-simple-style').textContent,/a\[href\^="\/admin"\]/);
});
