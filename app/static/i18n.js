(() => {
  'use strict';
  const valid = value => value === 'uz' || value === 'ru';
  const query = new URLSearchParams(location.search).get('lang');
  const cookie = (document.cookie || '').split(';').map(part => part.trim()).find(part => part.startsWith('relyqo_language='))?.split('=')[1];
  let saved;
  try { saved = localStorage.getItem('relyqo_language'); } catch {}
  let language = [query, saved, cookie].find(valid) || ((navigator.language || '').startsWith('uz') ? 'uz' : 'ru');
  function remember(value) {
    try { localStorage.setItem('relyqo_language', value); } catch {}
    document.cookie = 'relyqo_language=' + value + '; Path=/; Max-Age=31536000; SameSite=Lax' + (location.protocol === 'https:' ? '; Secure' : '');
  }
  // Run in the head before page scripts, including inline scripts and mobile links.
  document.documentElement.lang = language;
  remember(language);
  let dictionary = {}, pattern = null;
  const normalize = text => text.replace(/\s+/g, ' ').trim();
  const escape = text => text.replace(/[.*+?^{}()|[\]\\$]/g, '\\$&');
  function translate(text) {
    if (language !== 'uz' || typeof text !== 'string' || !/[А-Яа-яЁё]/.test(text)) return text;
    const value = normalize(text);
    if (Object.hasOwn(dictionary, value)) return text.match(/^\s*/)[0] + dictionary[value] + text.match(/\s*$/)[0];
    return pattern ? text.replace(pattern, match => dictionary[match]) : text;
  }
  window.relyqoT = translate;
  const skip = 'script,style,code,[data-user-content],[translate="no"],#placeName,#placeAddress,#organizationTitle,#organizationLead,#username,#name,#description,#assistantAnswer,#aiText,#analysis,#photoAnalysis';
  const attributes = ['placeholder', 'title', 'aria-label', 'alt'];
  function translateNode(node) {
    if (node.nodeType === 3) {
      if (!node.parentElement || node.parentElement.closest(skip)) return;
      const value = translate(node.nodeValue);
      if (value !== node.nodeValue) node.nodeValue = value;
    } else if (node.nodeType === 1) {
      if (node.closest('script,style,code,[translate="no"]')) return;
      // Input values and authored content stay intact; their form hints are interface text.
      if (!node.closest(skip) || node.matches('input,textarea,select')) {
        for (const attribute of attributes) if (node.hasAttribute(attribute)) {
          const value = node.getAttribute(attribute), translated = translate(value);
          if (value !== translated) node.setAttribute(attribute, translated);
        }
      }
      if (!node.matches('textarea,input')) for (const child of [...node.childNodes]) translateNode(child);
    }
  }
  function validation() {
    const owned = new WeakMap();
    function clear(event) {
      const field = event.target;
      if (owned.has(field)) {
        if (field.validationMessage === owned.get(field)) field.setCustomValidity('');
        owned.delete(field);
      }
    }
    document.addEventListener('input', clear, true);
    document.addEventListener('change', clear, true);
    document.addEventListener('reset', event => { for (const field of event.target.elements || []) clear({target:field}); }, true);
    document.addEventListener('invalid', event => {
      const field = event.target, state = field.validity;
      if (!state || typeof field.setCustomValidity !== 'function' || (state.customError && !owned.has(field))) return;
      clear(event);
      if (state.valid) return;
      const message = state.valueMissing ? (field.tagName === 'SELECT' ? 'Выберите значение из списка.' : 'Заполните это поле.')
        : state.typeMismatch ? (field.type === 'email' ? 'Введите корректный email.' : 'Введите корректную ссылку.')
        : state.tooShort ? 'Слишком короткое значение.' : state.tooLong ? 'Слишком длинное значение.'
        : state.rangeUnderflow ? 'Значение меньше допустимого.' : state.rangeOverflow ? 'Значение больше допустимого.'
        : state.badInput ? 'Введите число.' : state.patternMismatch ? 'Проверьте формат этого поля.' : 'Введите допустимое значение.';
      const translated = translate(message);
      field.setCustomValidity(translated); owned.set(field, translated);
    }, true);
  }
  function ui() {
    const bar = document.createElement('nav');
    bar.className = 'languageBar'; bar.setAttribute('aria-label', 'Til / Язык'); bar.setAttribute('translate', 'no');
    const label = document.createElement('label'); label.textContent = 'Til / Язык ';
    const select = document.createElement('select'); select.setAttribute('aria-label', 'Til / Язык');
    for (const [value, text] of [['ru', 'Русский'], ['uz', 'O‘zbekcha']]) {
      const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option);
    }
    select.value = language;
    select.addEventListener('change', () => {
      remember(select.value);
      // Account synchronization must not block switching for guests or a slow connection.
      try { fetch('/v1/auth/language', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({language:select.value}), keepalive:true}).catch(() => {}); } catch {}
      const url = new URL(location.href); url.searchParams.set('lang', select.value);
      location.assign(url.pathname + url.search + url.hash);
    });
    label.append(select); bar.append(label); document.body.prepend(bar);
    validation();
    if (language === 'uz') window.relyqoLanguageReady.then(() => {
      translateNode(document.documentElement);
      const observer = new MutationObserver(records => {
        observer.disconnect();
        for (const record of records) {
          if (record.type === 'childList') record.addedNodes.forEach(translateNode);
          else translateNode(record.target);
        }
        observe();
      });
      function observe() { observer.observe(document.documentElement, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:attributes}); }
      observe();
    });
  }
  async function loadDictionary() {
    for (let attempt = 0; attempt < 2; attempt++) {
      const controller = new AbortController(), deadline = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch('/static/i18n-uz.json?v=engagement-20261005', {signal:controller.signal, cache:attempt ? 'reload' : 'default'});
        if (!response.ok) throw Error('Dictionary unavailable');
        dictionary = await response.json();
        const keys = Object.keys(dictionary).filter(key => /[А-Яа-яЁё]/.test(key) && !key.includes('<') && !key.includes('">')).sort((a, b) => b.length - a.length).map(escape);
        pattern = new RegExp('(?<![\\p{L}])(?:' + keys.join('|') + ')(?![\\p{L}])', 'gu');
        return;
      } catch {
        if (attempt === 1) {
          // Reload the complete Russian page so direct bilingual controls cannot remain mixed.
          language = 'ru'; remember(language); document.documentElement.lang = language;
          const url = new URL(location.href); url.searchParams.set('lang', language);
          location.replace(url.pathname + url.search + url.hash);
        }
      } finally { clearTimeout(deadline); }
    }
  }
  window.relyqoLanguageReady = language === 'uz' ? loadDictionary() : Promise.resolve();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ui); else ui();
})();

