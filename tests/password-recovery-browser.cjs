/* UI recovery checks; API responses are simulated, no email is sent. Backend integration is in test_password_recovery.py. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.RELYQO_BASE_URL || 'http://127.0.0.1:8767';
const output = process.env.RELYQO_SCREENSHOTS;
(async()=>{
  const browser=await chromium.launch(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{});
  try{for(const width of [1440,390,320]){
    const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});
    const page=await context.newPage();const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('console',msg=>{if(msg.type()==='error'&&/Content Security Policy|Refused to/.test(msg.text()))errors.push(msg.text());});
    const capture=async name=>{assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,name+' overflow');if(output){fs.mkdirSync(output,{recursive:true});await page.screenshot({path:path.join(output,`${name}-${width}.png`),fullPage:true,animations:"disabled"});}};
    await page.goto(base+'/forgot-password');await capture('forgot-password');
    await page.route('**/v1/auth/forgot-password',r=>r.fulfill({status:503,json:{detail:'Отправка писем временно недоступна. Попробуйте позже.'}}));
    await page.getByLabel('Email',{exact:true}).fill('person@example.test');await page.locator('#forgotForm button').click();
    await page.waitForFunction(()=>document.getElementById('error').textContent.includes('недоступна'));
    await capture('forgot-unconfigured');
    await page.route('**/v1/auth/forgot-password',r=>r.fulfill({status:202,json:{message:'Если адрес подтверждён в RELYQO, на него придёт письмо. Проверьте входящие и папку «Спам».'}}));
    await page.locator('#email').press('Enter');await page.waitForFunction(()=>document.getElementById('message').textContent.includes('Если адрес'));
    await capture('forgot-accepted');
    await page.goto(base+'/reset-password');assert.equal(await page.locator('#resetForm').isVisible(),true);await capture('reset-code');
    await page.locator('#resetEmail').fill('person@example.test');await page.locator('#resetCode').fill('123456');
    await page.locator('#newPassword').fill('new-test-password');await page.locator('#confirmPassword').fill('different-password');await page.locator('#confirmPassword').press('Enter');
    assert.match(await page.locator('#error').innerText(),/не совпадают/);
    await page.route('**/v1/auth/reset-password',r=>r.fulfill({status:400,json:{detail:'Код недействителен или срок его действия истёк. Запросите новое письмо.'}}));
    await page.locator('#confirmPassword').fill('new-test-password');await page.locator('#confirmPassword').press('Enter');await page.locator('#retry').waitFor();await capture('reset-expired');
    await page.route('**/v1/auth/reset-password',r=>r.fulfill({json:{message:'Пароль изменён. Войдите с новым паролем. Все прежние сессии завершены.'}}));
    await page.locator('#resetForm button').click();await page.waitForFunction(()=>document.getElementById('resetForm').hidden);await capture('reset-success');
    await page.goto(base+'/verify-email#token='+'x'.repeat(43));await page.waitForFunction(()=>!location.hash);await capture('verify-email');
    await page.route('**/v1/auth/verify-email',r=>r.fulfill({json:{message:'Email подтверждён. Теперь он доступен для восстановления пароля.'}}));
    await page.locator('#verifyForm button').press('Enter');await page.waitForFunction(()=>document.getElementById('verifyForm').hidden);await capture('verify-success');
    await page.route('**/v1/consumer/dashboard',r=>r.fulfill({json:{username:'browser-fixture',favorites:[],ratings:[],photos:[]}}));
    await page.route('**/v1/auth/recovery-email',r=>r.request().method()==='GET'?r.fulfill({json:{email:null,verified:false}}):r.fulfill({status:202,json:{message:'Запрос принят. Откройте ссылку в письме, чтобы подтвердить адрес.'}}));
    await page.goto(base+'/me');await page.locator('#recoveryEmailForm').waitFor();await capture('recovery-account');
    await page.locator('#recoveryEmailForm [name=email]').fill('person@example.test');await page.locator('#recoveryEmailForm [name=current_password]').fill('test-password');await page.locator('#recoveryEmailForm button').click();await page.waitForFunction(()=>document.getElementById('recoveryEmailStatus').textContent.includes('Запрос принят'));
    assert.equal(await page.locator('#recoveryEmailForm [name=current_password]').inputValue(),'');
    await page.route('**/v1/auth/recovery-email',r=>r.fulfill({json:{email:'a'.repeat(64)+'@'+'b'.repeat(63)+'.'+'c'.repeat(63)+'.test',verified:true}}));
    await page.reload();await page.waitForFunction(()=>document.getElementById('recoveryEmailStatus').textContent.includes('Подтверждённый email'));
    await capture('recovery-long-email');
    assert.deepEqual(errors,[]);console.log(`PASS recovery ${width}px: request, errors, reset, confirmation, email binding, CSP, overflow`);
    await context.close();
  }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
