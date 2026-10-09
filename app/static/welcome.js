(() => {
  'use strict';
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
  const $ = id => document.getElementById(id);
  const t = text => window.relyqoT?.(text) || text;
  const destinations = new Set(['/', '/consumer', '/rate', '/nearby', '/community-rate', '/place', '/rankings', '/me', '/me/rating', '/me/requests', '/notifications']);
  function safeReturn(value) {
    if (!value.startsWith('/') || /[\\\u0000-\u0020\u007f]/.test(value)) return '/consumer';
    // Compare the raw path as well: URL parsing normalizes dot segments and backslashes.
    if (!destinations.has(value.split(/[?#]/)[0])) return '/consumer';
    return value;
  }
  const returnTo = safeReturn(new URLSearchParams(location.search).get('return_to') || '/consumer');
  let pending = false;
  function error(message) { $('authError').textContent = t(message); $('authError').hidden = false; }
  function mode(register) {
    if (pending) return;
    $('registerForm').hidden = !register; $('loginForm').hidden = register;
    $('showRegister').setAttribute('aria-pressed', String(register));
    $('showLogin').setAttribute('aria-pressed', String(!register));
    $('authError').hidden = true;
  }
  async function api(url, body) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, cache:'no-store', body:JSON.stringify(body), signal:controller.signal});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Проверьте введённые данные.');
      return data;
    } catch (failure) {
      if (failure.name === 'AbortError' || failure instanceof TypeError) throw Error('Не удалось связаться с сервером. Текст сохранён в форме. Проверьте соединение и повторите.');
      throw failure;
    } finally { clearTimeout(timer); }
  }
  async function finish() {
    // Preserve favorites collected in an earlier version, without delaying entry on network errors.
    let keys = [];
    try { const saved = JSON.parse(localStorage.getItem('relyqo_favorites_v1') || '[]'); if (Array.isArray(saved)) keys = saved; } catch {}
    await Promise.all(keys.filter(key => typeof key === 'string' && /^(manual|relyqo):/.test(key)).slice(0,100).map(object_key => api('/v1/consumer/favorites', {object_key, source:object_key.startsWith('manual:') ? 'MANUAL' : 'RELYQO_PARTNER', saved:true}).catch(() => {})));
    $('newRecoveryCode').textContent = '';
    // Do not leave the completed password form in browser back history.
    const destination = new URL(returnTo, location.origin);
    destination.searchParams.set('lang', document.documentElement.lang === 'uz' ? 'uz' : 'ru');
    location.replace(destination.pathname + destination.search + destination.hash);
  }
  async function submit(event, url) {
    event.preventDefault();
    if (pending) return;
    const body = Object.fromEntries(new FormData(event.currentTarget));
    body.language = document.documentElement.lang === 'uz' ? 'uz' : 'ru';
    pending = true; $('authError').hidden = true;
    const controls = [...document.querySelectorAll('#auth input, #auth button')];
    controls.forEach(control => control.disabled = true);
    $('authStatus').textContent = t('Подождите…'); $('authStatus').hidden = false;
    try {
      const data = await api(url, body);
      if (data.role !== 'CONSUMER') throw Error('Этот аккаунт предназначен для другой панели RELYQO');
      document.querySelectorAll('input[type=password]').forEach(input => input.value = '');
      if (data.recovery_code) {
        $('auth').hidden = true;
        $('newRecoveryCode').textContent = data.recovery_code;
        $('newRecoveryNotice').hidden = false;
        $('continueAfterRecovery').focus();
      } else await finish();
    } catch (failure) { error(failure.message); }
    finally { pending = false; controls.forEach(control => control.disabled = false); $('authStatus').hidden = true; }
  }
  $('showRegister').addEventListener('click', () => mode(true));
  $('showLogin').addEventListener('click', () => mode(false));
  $('loginForm').addEventListener('submit', event => submit(event, '/v1/auth/login'));
  $('registerForm').addEventListener('submit', event => submit(event, '/v1/consumer/register'));
  $('copyNewRecovery').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('newRecoveryCode').textContent); $('copyNewRecovery').textContent = t('Скопировано ✓'); }
    catch { error('Не удалось скопировать автоматически. Выделите код и скопируйте его вручную.'); }
  });
  $('continueAfterRecovery').addEventListener('click', async () => {
    if (pending) return;
    pending = true; $('continueAfterRecovery').disabled = true;
    await finish();
  });
  if (new URLSearchParams(location.search).get('mode') === 'login') mode(false);
})();
