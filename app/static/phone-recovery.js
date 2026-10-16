(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const language = document.documentElement.lang === 'uz' ? 'uz' : 'ru';
  const bind = location.pathname === '/account-phone';
  const ru = {
    title:'Восстановление по SMS', bindTitle:'Телефон для восстановления',
    intro:'Введите личный номер, который вы заранее подтвердили в настройках аккаунта.',
    bindIntro:'Подтвердите личный телефон, чтобы восстановить доступ при потере пароля. Старый номер действует до подтверждения нового.',
    country:'Страна номера', phone:'Мобильный номер', hint:'Выберите страну вашего номера. Можно ввести номер с кодом страны или в местном формате.',
    current:'Текущий пароль', send:'Получить SMS-код', code:'Код из SMS', newPassword:'Новый пароль — от 10 символов', confirm:'Повторите новый пароль',
    save:'Сохранить новый пароль', verify:'Подтвердить телефон', restart:'Другой номер или новый код',
    email:'Восстановить по email', reserve:'Использовать резервный код', account:'Войти в аккаунт',
    unavailable:'SMS пока недоступны. Используйте email или резервный код.', network:'Нет соединения. Попробуйте снова.',
    login:'Сначала войдите в аккаунт, чтобы привязать телефон.', verified:'Подтверждённый телефон: ', empty:'Телефон ещё не подтверждён.',
    mismatch:'Пароли не совпадают', invalid:'Код недействителен или истёк. Запросите новый SMS-код.',
    accepted:'Если номер подтверждён в аккаунте, на него придёт SMS. Код действует до 10 минут.',
    bindAccepted:'Запрос принят. Введите код из SMS для подтверждения номера.',
    done:'Пароль изменён. Войдите с новым паролем. Все прежние сессии завершены.',
    bound:'Телефон подтверждён. Теперь можно восстанавливать пароль по SMS.',
    badInput:'Проверьте страну, номер и заполненные поля.', rate:'Слишком много попыток. Попробуйте через час.', password:'Текущий пароль указан неверно', wait:'Повторить через ', seconds:' с',
  };
  const uz = {
    title:'SMS orqali tiklash', bindTitle:'Tiklash uchun telefon',
    intro:'Profil sozlamalarida oldindan tasdiqlagan shaxsiy raqamingizni kiriting.',
    bindIntro:'Parolni unutganda kirishni tiklash uchun shaxsiy telefoningizni tasdiqlang. Yangi raqam tasdiqlanmaguncha eski raqam amal qiladi.',
    country:'Raqam mamlakati', phone:'Mobil raqam', hint:'Raqamingiz mamlakatini tanlang. Raqamni mamlakat kodi bilan yoki mahalliy shaklda kiritishingiz mumkin.',
    current:'Joriy parol', send:'SMS-kod olish', code:'SMSdagi kod', newPassword:'Yangi parol — kamida 10 ta belgi', confirm:'Yangi parolni takrorlang',
    save:'Yangi parolni saqlash', verify:'Telefonni tasdiqlash', restart:'Boshqa raqam yoki yangi kod',
    email:'Email orqali tiklash', reserve:'Zaxira koddan foydalanish', account:'Profilga kirish',
    unavailable:'SMS hozircha mavjud emas. Email yoki zaxira koddan foydalaning.', network:'Ulanish yo‘q. Qayta urinib ko‘ring.',
    login:'Telefonni bog‘lash uchun avval profilingizga kiring.', verified:'Tasdiqlangan telefon: ', empty:'Telefon hali tasdiqlanmagan.',
    mismatch:'Parollar mos kelmaydi', invalid:'Kod yaroqsiz yoki muddati tugagan. Yangi SMS-kod so‘rang.',
    accepted:'Raqam profilda tasdiqlangan bo‘lsa, unga SMS keladi. Kod 10 daqiqagacha amal qiladi.',
    bindAccepted:'So‘rov qabul qilindi. Raqamni tasdiqlash uchun SMSdagi kodni kiriting.',
    done:'Parol o‘zgartirildi. Yangi parol bilan kiring. Barcha eski seanslar tugatildi.',
    bound:'Telefon tasdiqlandi. Endi parolni SMS orqali tiklash mumkin.',
    badInput:'Mamlakat, raqam va to‘ldirilgan maydonlarni tekshiring.', rate:'Urinishlar juda ko‘p. Bir soatdan keyin urinib ko‘ring.', password:'Joriy parol noto‘g‘ri', wait:'Qayta yuborish: ', seconds:' s',
  };
  const copy = language === 'uz' ? uz : ru;
  for (const element of document.querySelectorAll('[data-copy]')) element.textContent = copy[element.dataset.copy];
  $('title').textContent = bind ? copy.bindTitle : copy.title;
  document.title = $('title').textContent + ' — RELYQO';
  $('intro').textContent = bind ? copy.bindIntro : copy.intro;
  $('currentFields').hidden = !bind;
  $('currentPassword').required = bind;
  $('passwordFields').hidden = bind;
  for (const id of ['newPassword','confirmPassword']) { $(id).required = !bind; $(id).disabled = bind; }
  $('verify').textContent = bind ? copy.verify : copy.save;
  let challenge = null, available = false, retryAt = 0, timer = null;
  async function api(path, body) {
    let response;
    try { response = await fetch('/v1/auth/' + path, {method:body ? 'POST' : 'GET', cache:'no-store',
      ...(body ? {headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {})}); }
    catch { throw new Error(copy.network); }
    if (!response.ok) {
      throw new Error(response.status === 503 ? copy.unavailable : response.status === 429 ? copy.rate
        : response.status === 401 ? (path === 'recovery-phone' && body ? copy.password : copy.login)
        : response.status === 422 ? copy.badInput : copy.invalid);
    }
    return response.json();
  }
  function cooldown() {
    const remaining = Math.max(0, Math.ceil((retryAt - Date.now()) / 1000));
    $('send').disabled = !available || remaining > 0;
    $('send').textContent = remaining ? copy.wait + remaining + copy.seconds : copy.send;
    if (!remaining && timer) { clearInterval(timer); timer = null; }
  }
  async function initialize() {
    try {
      const options = await api('phone-options');
      if (!options.enabled || !options.regions.length) { $('status').textContent = copy.unavailable; return; }
      if (bind) {
        const account = await api('recovery-phone');
        $('status').textContent = account.verified ? copy.verified + account.phone : copy.empty;
      }
      let names;
      try { names = new Intl.DisplayNames([language], {type:'region'}); } catch { /* ISO codes remain readable. */ }
      const choices = options.regions.map(region => ({...region, label:(names?.of(region.code) || region.code) + ' (' + region.dial_code + ')'}));
      choices.sort((a,b) => a.label.localeCompare(b.label, language));
      for (const choice of choices) {
        const option = document.createElement('option'); option.value = choice.code; option.textContent = choice.label;
        $('region').append(option);
      }
      $('region').value = options.regions.some(r => r.code === 'UZ') ? 'UZ' : choices[0].code;
      available = true; $('phoneForm').hidden = false; cooldown();
    } catch (error) { $('error').textContent = error.message; }
  }
  $('phoneForm').addEventListener('submit', async event => {
    event.preventDefault();
    if (!available || Date.now() < retryAt || $('send').disabled) return;
    $('error').textContent = ''; $('send').disabled = true;
    try {
      const result = await api(bind ? 'recovery-phone' : 'forgot-password-phone', {
        phone:$('phone').value.trim(), region:$('region').value,
        ...(bind ? {current_password:$('currentPassword').value} : {}),
      });
      challenge = result.challenge;
      retryAt = Date.now() + Math.max(60, result.retry_after || 60) * 1000;
      if (timer) clearInterval(timer);
      timer = setInterval(cooldown, 1000);
      $('message').textContent = bind ? copy.bindAccepted : copy.accepted;
      $('phoneForm').hidden = true; $('codeForm').hidden = false; $('code').focus();
    } catch (error) { $('error').textContent = error.message; }
    finally { $('currentPassword').value = ''; cooldown(); }
  });
  $('codeForm').addEventListener('submit', async event => {
    event.preventDefault();
    if (!challenge || $('verify').disabled) return;
    $('error').textContent = '';
    if (!bind && $('newPassword').value !== $('confirmPassword').value) { $('error').textContent = copy.mismatch; return; }
    $('verify').disabled = true;
    try {
      await api(bind ? 'verify-phone' : 'reset-password-phone', {challenge, code:$('code').value.trim(),
        ...(!bind ? {new_password:$('newPassword').value, confirm_password:$('confirmPassword').value} : {}),
      });
      challenge = null; $('codeForm').reset(); $('codeForm').hidden = true;
      $('status').textContent = ''; $('message').textContent = bind ? copy.bound : copy.done;
      if (timer) clearInterval(timer);
    } catch (error) { $('error').textContent = error.message; }
    finally { $('verify').disabled = false; }
  });
  $('restart').addEventListener('click', () => {
    challenge = null; $('codeForm').reset(); $('codeForm').hidden = true; $('phoneForm').hidden = false;
    $('error').textContent = ''; $('message').textContent = ''; cooldown(); $('phone').focus();
  });
  window.addEventListener('pagehide', () => {
    challenge = null; $('codeForm').reset(); $('phoneForm').reset(); if (timer) clearInterval(timer);
  });
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  initialize();
})();
