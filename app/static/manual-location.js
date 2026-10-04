/* Location belongs to the organization; never save the visitor's GPS implicitly. */
window.relyqoManualLocation = ({loadMaps, onChange}) => {
  const $ = id => document.getElementById(id);
  const t = (ru, uz) => document.documentElement.lang === 'uz' ? uz : ru;
  const panel = $('manualLocation'), mapRoot = $('manualLocationMap');
  let map, marker, draft = null, confirmed = false, revision = 0, center = null;
  const valid = point => point && Number.isFinite(point.lat) && Number.isFinite(point.lng) && Math.abs(point.lat) <= 90 && Math.abs(point.lng) <= 180;
  const status = message => { $('manualLocationStatus').textContent = message; };
  function begin() {
    ++revision;
    for (const id of ['manualFindAddress','manualUseGps','manualOpenMap']) $(id).disabled = false;
    return revision;
  }
  const deadline = promise => new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Location timeout')), 15000);
    Promise.resolve(promise).then(resolve, reject).finally(() => clearTimeout(timer));
  });
  function update(point) {
    if (!valid(point)) return;
    draft = {...point}; confirmed = false; onChange(null);
    $('manualLocationConfirm').hidden = false;
    $('manualLocationClear').hidden = false;
    $('manualLocationPreview').hidden = false;
    $('manualLocationPreview').href = 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(point.lat + ',' + point.lng);
    status(t('Проверьте точку организации и подтвердите её.', 'Tashkilot nuqtasini tekshiring va tasdiqlang.'));
    drawPoint(point);
  }
  function drawPoint(point) {
    if (map) {
      map.setCenter(point); map.setZoom(17);
      if (!marker) {
        marker = new google.maps.Marker({map, position:point, draggable:true, title:t('Точка организации', 'Tashkilot nuqtasi')});
        marker.addListener('dragend', event => { if (event.latLng) { begin(); update({lat:event.latLng.lat(), lng:event.latLng.lng()}); } });
      } else { marker.setPosition(point); marker.setMap(map); }
    }
  }
  async function showMap(request) {
    if (request !== revision) return false;
    if (map) { mapRoot.hidden = false; if (draft) drawPoint(draft); return true; }
    if (!await deadline(loadMaps()) || request !== revision) return false;
    await deadline(google.maps.importLibrary('maps'));
    if (request !== revision) return false;
    mapRoot.hidden = false;
    map = new google.maps.Map(mapRoot, {center:draft || center || {lat:41.31,lng:69.28}, zoom:draft?17:center?14:11, mapTypeControl:false, streetViewControl:false, fullscreenControl:false, gestureHandling:'cooperative'});
    map.addListener('click', event => { if (event.latLng) { begin(); update({lat:event.latLng.lat(),lng:event.latLng.lng()}); } });
    if (draft) drawPoint(draft);
    return true;
  }
  function clear() {
    begin(); draft = null; confirmed = false; onChange(null);
    marker?.setMap(null);
    $('manualLocationResults').replaceChildren();
    $('manualLocationConfirm').hidden = true;
    $('manualLocationClear').hidden = true;
    $('manualLocationPreview').hidden = true;
    status(t('Без точки организация будет доступна в списке. С точкой — ещё и в поиске рядом.', 'Nuqtasiz tashkilot ro‘yxatda ko‘rinadi. Nuqta bilan yaqin atrof qidiruvida ham topiladi.'));
    for (const id of ['manualFindAddress','manualUseGps','manualOpenMap']) $(id).disabled = false;
  }
  $('manualOpenMap').addEventListener('click', async () => {
    const request = begin(); $('manualOpenMap').disabled = true;
    status(t('Открываем карту…', 'Xarita ochilmoqda…'));
    try {
      if (!await showMap(request)) throw new Error('Map unavailable');
      if (request === revision && !draft) status(t('Нажмите на здание организации на карте.', 'Xaritada tashkilot binosini bosing.'));
    } catch { if (request === revision) status(t('Карта недоступна. Можно указать точку по GPS, если вы у организации, или сохранить только адрес.', 'Xarita mavjud emas. Tashkilot yonida bo‘lsangiz GPS orqali nuqta belgilang yoki faqat manzilni saqlang.')); }
    finally { if (request === revision) $('manualOpenMap').disabled = false; }
  });
  $('manualFindAddress').addEventListener('click', async () => {
    const address = $('manualAddress').value.trim(), city = $('manualCity').value.trim();
    if (address.length < 3 || city.length < 2) { status(t('Сначала заполните город и адрес.', 'Avval shahar va manzilni kiriting.')); return; }
    const request = begin(); $('manualFindAddress').disabled = true;
    $('manualLocationResults').replaceChildren();
    status(t('Ищем адрес…', 'Manzil qidirilmoqda…'));
    try {
      if (!await deadline(loadMaps())) throw new Error('Map unavailable');
      const {Place} = await deadline(google.maps.importLibrary('places'));
      if (request !== revision) return;
      const data = await deadline(Place.searchByText({textQuery:[address, city, $('manualCountry').value].join(', '), fields:['location','formattedAddress','displayName'], maxResultCount:5, language:document.documentElement.lang === 'uz'?'uz':'ru'}));
      if (request !== revision) return;
      const places = (data.places || []).filter(place => place.location);
      status(places.length ? t('Выберите адрес из результатов Google Maps, затем подтвердите точку.', 'Google Maps natijalaridan manzilni tanlang, keyin nuqtani tasdiqlang.') : t('Адрес не найден. Укажите здание на карте или сохраните только адрес.', 'Manzil topilmadi. Xaritada binoni belgilang yoki faqat manzilni saqlang.'));
      for (const place of places) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'manualAddressResult'; button.setAttribute('data-user-content','');
        button.textContent = place.formattedAddress || place.displayName;
        button.addEventListener('click', async () => {
          const choice = begin();
          update({lat:place.location.lat(),lng:place.location.lng()});
          $('manualLocationResults').replaceChildren();
          try { await showMap(choice); } catch { /* The external map link remains available. */ }
        });
        $('manualLocationResults').append(button);
      }
    } catch { if (request === revision) status(t('Поиск адреса недоступен. Можно выбрать точку на карте или сохранить только адрес.', 'Manzil qidiruvi mavjud emas. Xaritada nuqta tanlang yoki faqat manzilni saqlang.')); }
    finally { if (request === revision) $('manualFindAddress').disabled = false; }
  });
  $('manualUseGps').addEventListener('click', () => {
    const request = begin(); $('manualUseGps').disabled = true;
    status(t('Определяем местоположение…', 'Joylashuv aniqlanmoqda…'));
    if (!navigator.geolocation) { $('manualUseGps').disabled = false; status(t('Геолокация недоступна. Найдите адрес или выберите точку на карте.', 'Joylashuv mavjud emas. Manzilni toping yoki xaritada nuqta tanlang.')); return; }
    navigator.geolocation.getCurrentPosition(async position => {
      if (request !== revision) return;
      $('manualUseGps').disabled = false;
      const {latitude, longitude, accuracy} = position.coords;
      if (!Number.isFinite(accuracy) || accuracy > 100 || !valid({lat:latitude,lng:longitude})) {
        status(t('GPS неточный. Найдите адрес или укажите здание на карте.', 'GPS aniqligi past. Manzilni toping yoki xaritada binoni belgilang.')); return;
      }
      update({lat:latitude,lng:longitude});
      try { await showMap(request); } catch { /* The consumer still confirms the point. */ }
    }, () => {
      if (request !== revision) return;
      $('manualUseGps').disabled = false;
      status(t('Геолокация недоступна. Найдите адрес или выберите точку на карте.', 'Joylashuv mavjud emas. Manzilni toping yoki xaritada nuqta tanlang.'));
    }, {enableHighAccuracy:true,timeout:12000,maximumAge:0});
  });
  $('manualLocationConfirm').addEventListener('click', () => {
    if (!draft) return;
    confirmed = true; onChange({...draft});
    $('manualLocationConfirm').hidden = true;
    status(t('Точка подтверждена. Организация будет находиться в поиске рядом.', 'Nuqta tasdiqlandi. Tashkilot yaqin atrof qidiruvida topiladi.'));
  });
  $('manualLocationClear').addEventListener('click', clear);
  for (const id of ['manualAddress','manualCity','manualCountry']) $(id).addEventListener('input', clear);
  $('manualDialog').addEventListener('close', clear);
  return {
    reset(options = {}) {
      clear(); center = valid(options.center) ? options.center : null;
      panel.open = false; mapRoot.hidden = true;
      if (valid(options.location)) { panel.open = true; update(options.location); }
    },
    validate() {
      if (!draft || confirmed) return true;
      panel.open = true;
      status(t('Подтвердите выбранную точку или нажмите «Убрать точку».', 'Tanlangan nuqtani tasdiqlang yoki «Nuqtani olib tashlash»ni bosing.'));
      $('manualLocationConfirm').focus(); return false;
    },
  };
};
