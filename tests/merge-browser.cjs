/* Integration checks. Run ONLY against an isolated local test database:
   creates consumer and Business Owner accounts, never sends email. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const base = process.env.RELYQO_BASE_URL;
assert.ok(base && ['127.0.0.1','localhost'].includes(new URL(base).hostname));
(async()=>{
  const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || 'msedge'});
  try {
    for(const width of [1440,390,320]) {
      const context=await browser.newContext({viewport:{width,height:900}});
      const page=await context.newPage(); const errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      const check=async()=>{
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`overflow ${width} ${page.url()}`);
        assert.deepEqual(errors,[]);
      };
      const password='merge-test-password-123';
      for(const email of [false,true]) {
        const username=`merge-${width}-${Date.now()}${email?'@example.test':''}`;
        const data={username,password,organization_name:'Merge Browser Business',category:'PROFESSIONAL_SERVICE',description:'Isolated integration test organization',address:'Test street 10',city:'Tashkent',country_code:'UZ',phone:'',website:'',latitude:41.3,longitude:69.25};
        const registered=await context.request.post(base+'/v1/business-owner/register',{data});
        assert.equal(registered.status(),200);
        await context.request.post(base+'/v1/auth/logout');
        await page.goto(base+'/business-owner'); await check();
        await page.locator('#loginForm [name=username]').fill(username.toUpperCase());
        await page.locator('#loginForm [name=password]').fill(password);
        await page.locator('#loginForm [name=password]').press('Enter');
        await page.locator('#dashboard').waitFor({state:'visible'});
        await page.waitForFunction(()=>document.getElementById('qrAccess').textContent==='ОЖИДАЕТ');
        assert.equal(await page.locator('#sideUsername').innerText(),username);
        for(const view of ['overview','profile','qr']) {
          const navigation=width<800?'.mobileBar':'.sideNav';
          await page.locator(`${navigation} [data-view=${view}]`).click();
          await check();
        }
        await context.request.post(base+'/v1/auth/logout');
      }
      await page.goto(base+'/me');
      const username=`consumer-${width}-${Date.now()}`;
      await page.locator('#registerForm [name=username]').fill(username);
      await page.locator('#registerForm [name=password]').fill(password);
      await page.locator('#registerForm button').click();
      await page.locator('#newRecoveryNotice').waitFor({state:'visible'});
      assert.match(await page.locator('#newRecoveryCode').innerText(),/^relyqo-/);
      await check();
      await page.locator('#continueAfterRecovery').click();
      await page.locator('#recoveryEmailForm').waitFor({state:'visible'});
      await page.locator('#recoveryPassword').fill(password);
      await page.locator('#recoveryCodeForm button').click();
      await page.locator('#recoveryCodeResult').waitFor({state:'visible'});
      assert.match(await page.locator('#recoveryCodeValue').innerText(),/^relyqo-/);
      await check();
      await page.locator('#logout').click();
      await page.locator('#loginForm').waitFor({state:'visible'});
      await check();
      await context.close();
      console.log(`PASS merged flows ${width}px: Business Owner email/username, workspace tabs, consumer signup, backup code, email settings, logout, overflow, JS errors`);
    }
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
