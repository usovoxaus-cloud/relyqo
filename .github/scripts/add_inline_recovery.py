from pathlib import Path

path = Path('app/static/community-rate.html')
text = path.read_text(encoding='utf-8')

old = '''        <div id="authError" class="authError hidden" role="alert"></div>
        <a id="loginLink" class="authFallback" href="/me">Открыть полный кабинет RELYQO →</a>'''
new = '''        <div id="authError" class="authError hidden" role="alert"></div>
        <div id="inlineRecovery" class="authForm hidden" aria-live="polite">
          <h3>Сохраните резервный код</h3>
          <p class="lead">Он понадобится, если вы забудете пароль. Код показывается только сейчас — сохраните его перед отправкой оценки.</p>
          <code id="inlineRecoveryValue" style="display:block;margin:12px 0;overflow-wrap:anywhere;color:#b8f8e4"></code>
          <button id="copyInlineRecovery" class="authButton secondary" type="button">Копировать код</button>
          <button id="continueInlineRecovery" class="authButton" type="button">Я сохранил код — отправить оценку</button>
        </div>
        <a id="loginLink" class="authFallback" href="/me">Открыть полный кабинет RELYQO →</a>'''
assert text.count(old) == 1, 'inline auth error anchor changed'
text = text.replace(old, new, 1)

old_consts = '''    const authError=document.querySelector('#authError');
    const loginLink=document.querySelector('#loginLink');'''
new_consts = '''    const authError=document.querySelector('#authError');
    const loginLink=document.querySelector('#loginLink');
    const authGrid=document.querySelector('#authGate .authGrid');
    const inlineRecovery=document.querySelector('#inlineRecovery');
    const inlineRecoveryValue=document.querySelector('#inlineRecoveryValue');'''
assert text.count(old_consts) == 1, 'inline auth const anchor changed'
text = text.replace(old_consts, new_consts, 1)

old_auth = '''        if(data.role!=='CONSUMER')throw new Error('Этот аккаунт предназначен для другой панели RELYQO');
        consumerAuthenticated=true;
        authGate.classList.add('hidden');
        authStatus.textContent=`Вход выполнен как ${data.username}. Отправляем оценку…`;
        if(pendingSubmission){pendingSubmission=false;await submitRating()}'''
new_auth = '''        if(data.role!=='CONSUMER')throw new Error('Этот аккаунт предназначен для другой панели RELYQO');
        consumerAuthenticated=true;
        if(data.recovery_code){
          authGrid.classList.add('hidden');
          inlineRecoveryValue.textContent=data.recovery_code;
          inlineRecovery.classList.remove('hidden');
          authStatus.textContent='Аккаунт создан. Сначала сохраните резервный код восстановления.';
          return;
        }
        authGate.classList.add('hidden');
        authStatus.textContent=`Вход выполнен как ${data.username}. Отправляем оценку…`;
        if(pendingSubmission){pendingSubmission=false;await submitRating()}'''
assert text.count(old_auth) == 1, 'authenticateInline anchor changed'
text = text.replace(old_auth, new_auth, 1)

old_listeners = '''    document.querySelector('#registerInline').addEventListener('submit',event=>{event.preventDefault();authenticateInline(event.currentTarget,'/v1/consumer/register')});
    document.querySelector('#loginInline').addEventListener('submit',event=>{event.preventDefault();authenticateInline(event.currentTarget,'/v1/auth/login')});'''
new_listeners = '''    document.querySelector('#copyInlineRecovery').addEventListener('click',async()=>{const button=document.querySelector('#copyInlineRecovery');try{await navigator.clipboard.writeText(inlineRecoveryValue.textContent);const original=button.textContent;button.textContent='Скопировано ✓';setTimeout(()=>button.textContent=original,1400)}catch{showAuthError('Не удалось скопировать автоматически. Выделите код и скопируйте его вручную.')}});
    document.querySelector('#continueInlineRecovery').addEventListener('click',async()=>{inlineRecovery.classList.add('hidden');authGrid.classList.remove('hidden');authGate.classList.add('hidden');authStatus.textContent='Резервный код сохранён. Отправляем оценку…';if(pendingSubmission){pendingSubmission=false;await submitRating()}});
    document.querySelector('#registerInline').addEventListener('submit',event=>{event.preventDefault();authenticateInline(event.currentTarget,'/v1/consumer/register')});
    document.querySelector('#loginInline').addEventListener('submit',event=>{event.preventDefault();authenticateInline(event.currentTarget,'/v1/auth/login')});'''
assert text.count(old_listeners) == 1, 'inline auth listener anchor changed'
text = text.replace(old_listeners, new_listeners, 1)
path.write_text(text, encoding='utf-8')

# Extend focused UI coverage.
path = Path('tests/test_consumer_recovery.py')
text = path.read_text(encoding='utf-8')
old = '''    recover = client.get("/recover")
    assert page.status_code == 200
    assert recover.status_code == 200'''
new = '''    recover = client.get("/recover")
    community = client.get("/community-rate?object_key=manual:test-place&source=MANUAL&name=Test&address=Test&category=OTHER")
    assert page.status_code == 200
    assert recover.status_code == 200
    assert community.status_code == 200'''
assert text.count(old) == 1, 'consumer recovery UI test anchor changed'
text = text.replace(old, new, 1)
old2 = '''    assert "Для потребителя резервный код показывается при регистрации" in recover.text
'''
new2 = '''    assert "Для потребителя резервный код показывается при регистрации" in recover.text
    assert 'id="inlineRecovery"' in community.text
    assert 'id="continueInlineRecovery"' in community.text
    assert "data.recovery_code" in community.text
'''
assert text.count(old2) == 1, 'consumer recovery test tail anchor changed'
text = text.replace(old2, new2, 1)
path.write_text(text, encoding='utf-8')
