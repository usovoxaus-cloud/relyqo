/* Run against a local server: RELYQO_BASE_URL=http://127.0.0.1:8766 node tests/ui-ux-browser.cjs
   Requires Playwright; set PLAYWRIGHT_CHANNEL=msedge to use installed Edge.
   Mutating API calls are intercepted, so these checks do not write application data. */
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const base = process.env.RELYQO_BASE_URL || 'http://127.0.0.1:8766';
const paths = ['/', '/nearby', '/me', '/rankings', '/community-rate', '/admin', '/review'];
(async () => {
  const browser = await chromium.launch(process.env.PLAYWRIGHT_CHANNEL ? {channel:process.env.PLAYWRIGHT_CHANNEL} : {});
  try {
    for (const width of [1440, 390, 320]) {
      const context = await browser.newContext({viewport:{width,height:900},serviceWorkers:"block",reducedMotion:"reduce"});
      let page = await context.newPage();
      const errors=[];
      page.on('pageerror', e=>errors.push(e.message));
      await page.route('**/v1/**', route => route.request().method()==='GET' ? route.continue() : route.fulfill({status:503,json:{detail:'Тестовый сбой сети'}}));
      for (const path of paths) {
        assert.equal((await page.goto(base+path)).status(),200,path);
        await page.waitForTimeout(200);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${path} overflow at ${width}`);
        assert.deepEqual(await page.locator('input:visible,select:visible,textarea:visible').evaluateAll(nodes=>nodes.filter(n=>!n.labels?.length&&!n.getAttribute('aria-label')).map(n=>n.id)),[],`${path} labels`);
      }
      await page.goto(base+'/nearby');
      await page.locator('.searchSettings summary').click();
      await page.locator('#radius').fill('10');
      await page.locator('#resultLimit').selectOption('50');
      await page.locator('.searchSettings summary').click();
      for (const id of ['mapCard','listCard']) {
        await page.locator('.viewLinks a[href="#'+id+'"]').click();
        assert.ok(await page.locator('#'+id).evaluate(e=>Math.abs(e.getBoundingClientRect().top)<80),'Direct jump to '+id);
      }
      await page.route('**/v1/public/rated-organizations?*',r=>r.fulfill({json:{items:[],total:0,has_more:false}}));
      await page.locator('#ratedOrganizationsTab').click();
      await page.waitForFunction(()=>document.querySelector('#status').textContent==='Каталог с оценками загружен');
      assert.equal(await page.locator('#ratedOrganizationsTab').getAttribute('aria-selected'),'true');
      await page.goto(base+'/community-rate');
      assert.equal(await page.locator('#chooseOrganization').isVisible(),true);
      assert.equal(await page.locator('#formCard').isVisible(),false);
      assert.equal(await page.locator('#submit').isDisabled(),true);
      await page.goto(base+'/community-rate?object_key=manual:test&source=MANUAL&name=Test');
      await page.locator('input[type=range]').first().focus();
      await page.keyboard.press('ArrowRight');
      assert.equal(await page.locator('input[type=range]').first().inputValue(),'8');
      await page.locator('#submit').click();
      assert.equal(await page.locator('#authGate').isVisible(),true);
      assert.equal(await page.locator('input[type=range]').first().inputValue(),'8');
      await page.goto(base+'/me');
      await page.locator('.accessHelp summary').click();
      assert.match(await page.locator('.accessHelp').innerText(),/Автоматический сброс пароля потребителя пока недоступен/);
      await page.goto(base+'/review');
      let loginRequests=0;
      await page.route('**/v1/auth/login',r=>{loginRequests++;return r.fulfill({status:401,json:{detail:'Тест: неверный пароль'}})});
      await page.locator('#password').fill('test-password');
      await page.locator('#password').press('Enter');
      await page.waitForFunction(()=>document.querySelector('#error').textContent.includes('Тест:'));
      assert.equal(loginRequests,1,'Enter submits login exactly once');
      await page.close();
      page = await context.newPage();
      page.on('pageerror',e=>errors.push(e.message));
      await page.route('**/v1/**',route=>route.request().method()==='GET'?route.continue():route.fulfill({status:503,json:{detail:'Тестовый сбой сети'}}));
      await page.route('**/v1/auth/me',r=>r.fulfill({json:{role:'RELYQO_REVIEWER',username:'review-test'}}));
      await page.route('**/v1/review/ratings',r=>r.fulfill({json:{items:[],count:0}}));
      await page.goto(base+'/review');
      for (const [field,endpoint,error] of [['newPassword','change-password','passwordError'],['recoveryPassword','recovery-code','recoveryError']]) {
        let requests=0;
        await page.route('**/v1/auth/'+endpoint,r=>{requests++;return r.fulfill({status:503,json:{detail:'Тестовый сбой сети'}})});
        await page.locator('#'+field).fill('test-password-123');
        await page.locator('#'+field).press('Enter');
        await page.waitForFunction(id=>document.getElementById(id).textContent.includes('Тестовый'),error);
        assert.equal(requests,1,`Enter submits ${endpoint} exactly once`);
      }
      await page.route('**/v1/consumer/dashboard',r=>r.fulfill({json:{username:'test',favorites:[{name:'Избранная организация',object_key:'manual:test',source:'MANUAL',href:'/nearby'}],ratings:[],photos:[]}}));
      await page.route('**/v1/consumer/favorites',r=>r.abort('failed'));
      await page.goto(base+'/me');
      await page.locator('#favorites button').click();
      await page.locator('#favorites [role=alert]').waitFor();
      assert.match(await page.locator('#favorites [role=alert]').innerText(),/Не удалось удалить/);
      assert.equal(await page.locator('#favorites button').isEnabled(),true,'Retry remains possible');
      assert.equal(await page.locator('#favorites button').count(),1,'Favorite retained on failure');
      assert.deepEqual(errors,[],`JS errors at ${width}`);
      console.log(`PASS ${width}px: seven pages, labels, overflow, rating gate, recovery help, Review Enter, favorite failure`);
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
