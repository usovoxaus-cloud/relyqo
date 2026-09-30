// Live Google Places evidence. Never stored or copied into a consumer's own scores.
(() => {
  let loading, attempt = 0;
  const t = (ru, uz) => document.documentElement.lang === 'uz' ? uz : ru;
  const timed = (promise, milliseconds = 12000) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(Error('Google timeout')), milliseconds);
    Promise.resolve(promise).then(resolve, reject).finally(() => clearTimeout(timer));
  });
  async function load() {
    if (window.google?.maps?.importLibrary) return window.google.maps.importLibrary('places');
    if (!loading) loading = (async () => {
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
      let response;
      try { response = await fetch('/v1/public/maps-config', {cache:'no-store', signal:controller.signal}); }
      finally { clearTimeout(timer); }
      const config = await response.json();
      if (!response.ok || !config.configured || !config.browser_key) throw Error('Google unavailable');
      await new Promise((resolve, reject) => {
        const script = document.createElement('script'), callback = `relyqoGoogleRatingReady${++attempt}`;
        const finish = error => {
          clearTimeout(deadline); window[callback] = () => {}; script.onerror = null;
          if (error) {script.remove(); reject(error);} else resolve();
        };
        const deadline = setTimeout(() => finish(Error('Google timeout')), 12000);
        window[callback] = () => finish();
        script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(config.browser_key)}&loading=async&callback=${callback}&v=weekly`;
        script.async = true; script.onerror = () => finish(Error('Google unavailable'));
        document.head.append(script);
      });
    })().catch(error => {loading = null; throw error;});
    await loading;
    return window.google.maps.importLibrary('places');
  }
  function safeLink(value) {
    try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; }
    catch { return null; }
  }
  function node(tag, text, className) {
    const item = document.createElement(tag); item.textContent = text;
    if (className) item.className = className;
    return item;
  }
  function render(root, place, compact = false) {
    root.replaceChildren(); root.className = 'googleRating'; root.setAttribute('aria-live', 'polite');
    const brand = node('span', 'Google Maps', 'googleRatingBrand'); brand.setAttribute('translate', 'no');
    root.append(brand);
    if (!compact) {
      const identity = node('p', [place.displayName, place.formattedAddress].filter(Boolean).join(' · '), 'googleRatingPlace');
      identity.setAttribute('translate', 'no'); root.append(identity);
    }
    const count = Number.isInteger(place.userRatingCount) && place.userRatingCount >= 0 ? place.userRatingCount : null;
    const score = typeof place.rating === 'number' && Number.isFinite(place.rating) && place.rating >= 1 && place.rating <= 5 && count !== 0 ? place.rating : null;
    root.append(node('strong', score === null ? t('Нет оценки Google', 'Google bahosi yo‘q') : `★ ${score.toFixed(1)}/5`, 'googleRatingScore'));
    root.append(node('p', count === null ? t('Число оценок недоступно', 'Baholar soni mavjud emas') : t(`${count} оценок в Google`, `Google’da ${count} ta baho`), 'googleRatingCount'));
    const href = safeLink(place.googleMapsURI);
    if (href) { const link = node('a', t('Посмотреть в Google Maps', 'Google Maps’da ko‘rish')); link.href = href; link.target = '_blank'; link.rel = 'noopener'; root.append(link); }
    for (const attribution of place.attributions || []) {
      if (!attribution.provider) continue;
      const url = safeLink(attribution.providerURI), label = node(url ? 'a' : 'span', attribution.provider, 'googleRatingProvider');
      if (url) {label.href = url; label.target = '_blank'; label.rel = 'noopener';}
      label.setAttribute('translate', 'no'); root.append(label);
    }
    if (!compact) root.append(node('p', t('Общий рейтинг Google. Ваши оценки RELYQO по отдельным критериям вы выбираете сами.', 'Google umumiy reytingi. RELYQO mezonlari bo‘yicha o‘z baholaringizni o‘zingiz tanlaysiz.'), 'googleRatingNote'));
  }
  const letters = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'j','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'x','ц':'ts','ч':'ch','ш':'sh','щ':'sh','ъ':'','ы':'i','ь':'','э':'e','ю':'yu','я':'ya','ў':'o','қ':'q','ғ':'g','ҳ':'h'};
  function normalized(value) {
    return String(value || '').toLowerCase().replace(/[а-яёўқғҳ]/g, c => letters[c]).replace(/['‘’`ʻʼ]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
  }
  function component(place, kind) { return (place.addressComponents || []).find(c => (c.types || []).includes(kind)); }
  function matches(place, reference) {
    if (normalized(place.displayName) !== normalized(reference.name)) return false;
    if (component(place, 'country')?.shortText !== (reference.country_code || 'UZ')) return false;
    const knownLocation = [reference.latitude, reference.longitude].every(v => v !== null && v !== undefined && String(v).trim() !== '' && Number.isFinite(Number(v)));
    if (knownLocation && place.location) {
      const north = (place.location.lat() - reference.latitude) * 111000;
      const east = (place.location.lng() - reference.longitude) * 111000 * Math.cos(Number(reference.latitude) * Math.PI / 180);
      return Math.hypot(north, east) <= 75;
    }
    const cityName = value => normalized(value).replace(/^toshkent$/, 'tashkent').replace(/^samarqand$/, 'samarkand');
    const city = component(place, 'locality')?.longText;
    if (!reference.city || !city || cityName(city) !== cityName(reference.city)) return false;
    const address = new Set(normalized(reference.address).split(' '));
    const number = normalized(component(place, 'street_number')?.longText);
    const generic = new Set(['street','st','ulitsa','ul','kochasi','kocha','avenue','prospekt','pr','road']);
    const route = normalized(component(place, 'route')?.longText).split(' ').filter(word => word && !generic.has(word));
    return Boolean(number && address.has(number) && route.length && route.every(word => address.has(word)));
  }
  async function mount(root, reference) {
    if (!root) return;
    const generation = String(Number(root.dataset.generation || 0) + 1); root.dataset.generation = generation;
    const current = () => root.dataset.generation === generation;
    root.className = 'googleRating'; root.setAttribute('aria-live', 'polite');
    root.replaceChildren(node('p', t('Загружаем рейтинг Google…', 'Google reytingi yuklanmoqda…')));
    try {
      const {Place} = await timed(load());
      let place;
      const fields = ['id','displayName','formattedAddress','rating','userRatingCount','googleMapsURI','attributions'];
      if (reference.google_place_id) {
        place = new Place({id:reference.google_place_id});
        await timed(place.fetchFields({fields}));
      } else if (reference.name && reference.address) {
        const result = await timed(Place.searchByText({textQuery:`${reference.name}, ${reference.address}, Uzbekistan`,
          fields:[...fields, 'location', 'addressComponents'], maxResultCount:5, region:'UZ', language:'ru'}));
        const candidates = [...new Map((result.places || []).filter(p => matches(p, reference)).map(p => [p.id,p])).values()];
        if (candidates.length === 1) place = candidates[0];
      }
      if (!current()) return;
      if (!place) {
        root.replaceChildren(node('p', t('Рейтинг Google не показан: точное совпадение заведения не найдено.', 'Google reytingi ko‘rsatilmagan: aynan shu joy topilmadi.')));
        return;
      }
      render(root, place);
    } catch {
      if (!current()) return;
      root.replaceChildren(node('p', t('Рейтинг Google временно недоступен. Вы можете оставить свою оценку.', 'Google reytingi vaqtincha mavjud emas. O‘z bahoingizni qoldirishingiz mumkin.')));
      const retry = node('button', t('Повторить', 'Qayta urinish')); retry.type = 'button';
      retry.addEventListener('click', () => mount(root, reference)); root.append(retry);
    }
  }
  async function forObject(root, objectKey) {
    if (!root || !objectKey) return;
    const generation = String(Number(root.dataset.generation || 0) + 1); root.dataset.generation = generation;
    const current = () => root.dataset.generation === generation;
    root.className = 'googleRating'; root.setAttribute('aria-live', 'polite');
    root.replaceChildren(node('p', t('Загружаем рейтинг Google…', 'Google reytingi yuklanmoqda…')));
    try {
      const response = await timed(fetch(`/v1/public/place?object_key=${encodeURIComponent(objectKey)}`, {cache:'no-store'}));
      if (!response.ok) throw Error('Profile unavailable');
      const profile = await response.json();
      if (!current()) return;
      await mount(root, profile.google_reference || {});
    } catch { if (current()) root.textContent = t('Рейтинг Google пока недоступен.', 'Google reytingi hozircha mavjud emas.'); }
  }
  window.relyqoGoogleRating = {mount, forObject, render};
})();
