// Run against an initialized local server with Playwright installed.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const base = process.env.RELYQO_TEST_URL || 'http://127.0.0.1:8765';
const mapsStub = `window.google = {maps: {
 Map: class {constructor(el) {el.innerHTML='<div role="region" aria-label="Map">Test map</div>'} setCenter() {} setZoom() {}},
 Marker: class {setMap() {} addListener() {}},
 importLibrary: async () => ({Place: {searchNearby:async()=>({places:[]})}, SearchNearbyRankPreference:{POPULARITY:'POPULARITY'}})
}}; window.relyqoGoogleMapReady();`;

(async () => {
 const browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
 try {
  for (const scenario of ['missing', 'timeout', 'network', 'auth', 'success', 'denied']) {
   const context = await browser.newContext({permissions:scenario==='denied'?[]:['geolocation'], geolocation:{latitude:41.2995,longitude:69.2401}});
   const page = await context.newPage();
   const errors=[]; page.on('pageerror', e=>errors.push(e.message));
   // Use a short simulated timeout without waiting twelve seconds per case.
   await page.addInitScript(() => {const original=window.setTimeout; window.setTimeout=(fn,ms,...args)=>original(fn,ms===12000?150:ms,...args)});
   let configured = scenario !== 'missing';
   await page.route('**/v1/public/maps-config', route=>route.fulfill({json:{configured,browser_key:configured?'test-key':null}}));
   await page.route('https://maps.googleapis.com/**', route=> {
    if(scenario==='network') return route.abort();
    return route.fulfill({contentType:'application/javascript',body:scenario==='timeout'?'/* no callback */':scenario==='auth'?'window.gm_authFailure();':mapsStub});
   });
   await page.goto(base+'/nearby');
   await page.waitForFunction(()=>!document.querySelector('#locate').disabled);
   const status=await page.locator('#status').innerText();
   const error=await page.locator('#error').innerText();
   if(scenario==='success') {
    assert.equal(await page.locator('#map.googleReady').count(),1);
    // Google can reject authorization after the load callback has succeeded.
    await page.evaluate(()=>window.gm_authFailure());
    assert.equal(await page.locator('#map.googleReady').count(),0);
    assert.equal(await page.locator('#markers').count(),1);
   } else if(scenario==='denied') assert.match(error,/геолокации/);
   else {
    assert.match(status,/Готово/);
    assert.match(error,scenario==='missing'?/отсутствует ключ/:scenario==='timeout'?/время ожидания/:scenario==='auth'?/отклонила доступ/:/временно недоступна/);
    assert.equal(await page.locator('#markers').count(),1);
   }
   if(scenario==='missing') {
    configured=true;
    await page.locator('#locate').click();
    await page.waitForFunction(()=>!document.querySelector('#locate').disabled);
    assert.equal(await page.locator('#map.googleReady').count(),1,'retry must reload configuration');
   }
   assert.deepEqual(errors,[]);
   console.log('PASS map scenario: '+scenario);
   await context.close();
  }
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
