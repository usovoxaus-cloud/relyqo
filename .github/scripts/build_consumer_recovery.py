from pathlib import Path


# Backend: issue a one-time recovery code at consumer registration,
# allow consumers to rotate it while authenticated, and accept it for recovery.
path = Path("app/main.py")
text = path.read_text(encoding="utf-8")
start = text.index('@app.post("/v1/consumer/register")')
end = text.index('@app.post("/v1/business-owner/register")', start)
block = text[start:end]
old = "    raw_token = secrets.token_urlsafe(32)\n    db.add_all(\n"
new = (
    "    raw_token = secrets.token_urlsafe(32)\n"
    '    raw_recovery_code = f"relyqo-{secrets.token_urlsafe(32)}"\n'
    "    user.recovery_code_hash = token_hash(raw_recovery_code)\n"
    "    user.recovery_code_created_at = datetime.utcnow()\n"
    "    db.add_all(\n"
)
assert block.count(old) == 1, "consumer registration token anchor changed"
block = block.replace(old, new, 1)
old_return = '    return {"username": user.username, "role": user.role}\n'
new_return = (
    "    return {\n"
    '        "username": user.username,\n'
    '        "role": user.role,\n'
    '        "recovery_code": raw_recovery_code,\n'
    '        "recovery_code_warning": "SAVE_NOW_SHOWN_ONCE",\n'
    "    }\n"
)
assert block.count(old_return) == 1, "consumer registration return anchor changed"
block = block.replace(old_return, new_return, 1)
text = text[:start] + block + text[end:]

old_roles = "    user = session_user(relyqo_session, db, {OWNER_ROLE, REVIEWER_ROLE})\n"
new_roles = "    user = session_user(relyqo_session, db, {OWNER_ROLE, REVIEWER_ROLE, CONSUMER_ROLE})\n"
assert text.count(old_roles) == 1, "recovery-code role anchor changed"
text = text.replace(old_roles, new_roles, 1)

old_valid = "    valid_role = bool(user and user.role in {OWNER_ROLE, REVIEWER_ROLE})\n"
new_valid = "    valid_role = bool(user and user.role in {OWNER_ROLE, REVIEWER_ROLE, CONSUMER_ROLE})\n"
assert text.count(old_valid) == 1, "recover role anchor changed"
text = text.replace(old_valid, new_valid, 1)
path.write_text(text, encoding="utf-8")


# Consumer cabinet: show initial code once, provide recovery link and allow rotation.
path = Path("app/static/me.html")
text = path.read_text(encoding="utf-8")
old_help = '<details class="accessHelp"><summary>Забыли пароль? Помощь со входом</summary><p>Проверьте сохранённые пароли в браузере или менеджере паролей: найдите запись RELYQO и используйте сохранённое имя пользователя.</p><p>Автоматический сброс пароля потребителя пока недоступен. Если пароль не сохранён, восстановить этот аккаунт через сайт сейчас нельзя. Новый аккаунт не восстановит прежние избранное и историю.</p><p>Для владельца или Review с заранее сохранённым резервным кодом: <a href="/recover">восстановить служебный доступ</a>.</p></details>'
new_help = '<details class="accessHelp"><summary>Забыли пароль? Восстановить доступ</summary><p>Если у вас сохранён резервный код RELYQO, вы можете установить новый пароль без обращения в поддержку.</p><p><a href="/recover?account=consumer">Восстановить пароль по резервному коду →</a></p><p>Резервный код показывается при регистрации и его можно заменить в разделе безопасности после входа.</p></details>'
assert text.count(old_help) == 1, "consumer login help anchor changed"
text = text.replace(old_help, new_help, 1)

old_error = '    <div id="authError" class="error hidden" role="alert"></div>\n    <section id="dashboard" class="hidden">\n'
new_error = '''    <div id="authError" class="error hidden" role="alert"></div>
    <section id="newRecoveryNotice" class="card section hidden" aria-live="polite">
      <p class="eyebrow">ВАЖНО · ПОКАЗЫВАЕТСЯ ОДИН РАЗ</p><h2>Сохраните резервный код</h2>
      <p class="lead">Он позволит восстановить ваш аккаунт, если вы забудете пароль. RELYQO хранит только защищённый отпечаток кода и не сможет показать этот код повторно.</p>
      <div class="answer"><code id="newRecoveryCode" style="display:block;overflow-wrap:anywhere"></code></div>
      <div class="itemActions"><button id="copyNewRecovery" class="button secondary" type="button">Копировать код</button><button id="continueAfterRecovery" class="button" type="button">Я сохранил код</button></div>
    </section>
    <section id="dashboard" class="hidden">
'''
assert text.count(old_error) == 1, "auth error anchor changed"
text = text.replace(old_error, new_error, 1)

old_account = '      <div class="accountBar"><span>Выполнен вход: <b id="username"></b></span><button id="logout" class="button secondary" type="button">Выйти</button></div>\n      <div class="dashboardGrid">\n'
new_account = '''      <div class="accountBar"><span>Выполнен вход: <b id="username"></b></span><button id="logout" class="button secondary" type="button">Выйти</button></div>
      <section class="card section">
        <p class="eyebrow">БЕЗОПАСНОСТЬ АККАУНТА</p><h2>Резервный код восстановления</h2>
        <p class="lead">Создайте новый одноразовый резервный код и сохраните его в надёжном месте. Новый код автоматически отменяет предыдущий.</p>
        <form id="recoveryCodeForm"><label class="field">Текущий пароль<input id="recoveryPassword" name="current_password" type="password" minlength="8" autocomplete="current-password" required placeholder="Введите текущий пароль"></label><button class="button" type="submit">Создать новый резервный код</button></form>
        <div id="recoveryCodeResult" class="answer hidden" aria-live="polite"><b>Новый резервный код — сохраните сейчас:</b><code id="recoveryCodeValue" style="display:block;margin:10px 0;overflow-wrap:anywhere"></code><button id="copyRecoveryCode" class="button secondary" type="button">Копировать код</button></div>
      </section>
      <div class="dashboardGrid">
'''
assert text.count(old_account) == 1, "account bar anchor changed"
text = text.replace(old_account, new_account, 1)

old_auth = "    async function authenticate(form,url){hideError();const body=Object.fromEntries(new FormData(form));try{const data=await api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(data.role!=='CONSUMER')throw new Error('Этот аккаунт предназначен для другой панели RELYQO');await importLocalFavorites();if(returnTo){location.href=returnTo;return}await loadDashboard()}catch(error){showError(error.message)}}\n"
new_auth = '''    async function finishAuthenticatedFlow(){await importLocalFavorites();if(returnTo){location.href=returnTo;return}await loadDashboard()}
    async function copyRecoveryValue(value,button){try{await navigator.clipboard.writeText(value);const original=button.textContent;button.textContent='Скопировано ✓';setTimeout(()=>button.textContent=original,1400)}catch{showError('Не удалось скопировать автоматически. Выделите код и скопируйте его вручную.')}}
    async function authenticate(form,url){hideError();const body=Object.fromEntries(new FormData(form));try{const data=await api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(data.role!=='CONSUMER')throw new Error('Этот аккаунт предназначен для другой панели RELYQO');if(data.recovery_code){$('auth').classList.add('hidden');$('newRecoveryCode').textContent=data.recovery_code;$('newRecoveryNotice').classList.remove('hidden');return}await finishAuthenticatedFlow()}catch(error){showError(error.message)}}
'''
assert text.count(old_auth) == 1, "authenticate anchor changed"
text = text.replace(old_auth, new_auth, 1)

listener_anchor = "    $('ratingType').addEventListener('change',renderRatingHistory);"
assert text.count(listener_anchor) == 1, "listener anchor changed"
extra_listeners = '''    $('copyNewRecovery').addEventListener('click',()=>copyRecoveryValue($('newRecoveryCode').textContent,$('copyNewRecovery')));
    $('continueAfterRecovery').addEventListener('click',async()=>{$('newRecoveryNotice').classList.add('hidden');await finishAuthenticatedFlow()});
    $('recoveryCodeForm').addEventListener('submit',async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{hideError();const data=await api('/v1/auth/recovery-code',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_password:$('recoveryPassword').value})});$('recoveryPassword').value='';$('recoveryCodeValue').textContent=data.recovery_code;$('recoveryCodeResult').classList.remove('hidden')}catch(error){showError(error.message)}finally{button.disabled=false}});
    $('copyRecoveryCode').addEventListener('click',()=>copyRecoveryValue($('recoveryCodeValue').textContent,$('copyRecoveryCode')));
'''
text = text.replace(listener_anchor, extra_listeners + listener_anchor, 1)
path.write_text(text, encoding="utf-8")


# Recovery page: make the existing one-time-code flow explicitly support consumers.
path = Path("app/static/recover.html")
text = path.read_text(encoding="utf-8")
replacements = {
    "Используйте резервный код, который был заранее создан в защищённой панели. После восстановления код и все старые сеансы станут недействительными.": "Используйте резервный код RELYQO, сохранённый при регистрации или созданный в разделе безопасности аккаунта. После восстановления код и все старые сеансы станут недействительными.",
    'placeholder="fregat-owner или relyqo-reviewer"': 'placeholder="Ваше имя пользователя RELYQO"',
    'Пароль изменён. Резервный код использован и больше не действует.<div class="links"><a href="/owner">Войти как владелец</a><a href="/review">Открыть RELYQO Review</a></div>': 'Пароль изменён. Резервный код использован и больше не действует.<div class="links"><a href="/me">Войти в Мой RELYQO</a><a href="/owner">Войти как владелец</a><a href="/review">Открыть RELYQO Review</a></div>',
    "Для сотрудника Fregat пароль сбрасывает владелец в панели Owner. Резервный код предназначен только для владельца и независимого RELYQO Review.": "Для потребителя резервный код показывается при регистрации и может быть заменён в Мой RELYQO → Безопасность. Для сотрудника Fregat пароль по-прежнему сбрасывает владелец в панели Owner.",
}
for old, new in replacements.items():
    assert text.count(old) == 1, f"recover page anchor changed: {old[:30]}"
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")


# Focused API + static UI tests.
Path("tests/test_consumer_recovery.py").write_text(
    '''import uuid

from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


def test_consumer_has_one_time_self_service_recovery():
    Base.metadata.create_all(engine)
    username = f"recover-consumer-{uuid.uuid4().hex[:10]}"
    original_password = "consumer-original-123"
    replacement_password = "consumer-recovered-456"
    client = TestClient(app)

    registered = client.post(
        "/v1/consumer/register",
        json={"username": username, "password": original_password},
    )
    assert registered.status_code == 200
    initial_code = registered.json()["recovery_code"]
    assert initial_code.startswith("relyqo-")
    assert registered.json()["recovery_code_warning"] == "SAVE_NOW_SHOWN_ONCE"

    rotated = client.post(
        "/v1/auth/recovery-code",
        json={"current_password": original_password},
    )
    assert rotated.status_code == 200
    rotated_code = rotated.json()["recovery_code"]
    assert rotated_code.startswith("relyqo-")
    assert rotated_code != initial_code

    recovery_client = TestClient(app)
    old_code = recovery_client.post(
        "/v1/auth/recover",
        json={
            "username": username,
            "recovery_code": initial_code,
            "new_password": replacement_password,
        },
    )
    assert old_code.status_code == 401

    recovered = recovery_client.post(
        "/v1/auth/recover",
        json={
            "username": username,
            "recovery_code": rotated_code,
            "new_password": replacement_password,
        },
    )
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "ACCOUNT_RECOVERED"
    assert client.get("/v1/auth/me").status_code == 401

    reused = recovery_client.post(
        "/v1/auth/recover",
        json={
            "username": username,
            "recovery_code": rotated_code,
            "new_password": "consumer-third-password-789",
        },
    )
    assert reused.status_code == 401

    assert TestClient(app).post(
        "/v1/auth/login",
        json={"username": username, "password": original_password},
    ).status_code == 401
    assert TestClient(app).post(
        "/v1/auth/login",
        json={"username": username, "password": replacement_password},
    ).status_code == 200


def test_consumer_recovery_ui_is_visible():
    client = TestClient(app)
    page = client.get("/me")
    recover = client.get("/recover")
    assert page.status_code == 200
    assert recover.status_code == 200
    assert "Восстановить пароль по резервному коду" in page.text
    assert 'id="recoveryCodeForm"' in page.text
    assert 'id="newRecoveryNotice"' in page.text
    assert "Войти в Мой RELYQO" in recover.text
    assert "Для потребителя резервный код показывается при регистрации" in recover.text
''',
    encoding="utf-8",
)
