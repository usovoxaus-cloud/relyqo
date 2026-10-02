/* Rating entrance reuses the live search and map; no coordinates enter the URL or storage. */
(() => {
  const params = new URLSearchParams(location.search);
  const mode = params.get('find') || (location.pathname === '/rate' ? 'here' : null);
  if (!['here','search','nearby','map'].includes(mode) || !document.getElementById('directoryPanel')) return;
  if (document.body.classList.contains('ratingDiscovery')) return;
  document.body.classList.add('ratingDiscovery');
  const t = (ru, uz) => document.documentElement.lang === 'uz' ? uz : ru;
  const node = (tag, text, id) => {const n=document.createElement(tag);n.textContent=text;if(id)n.id=id;return n;};
  document.title = t('Найти организацию для оценки — RELYQO', 'Baholash uchun tashkilot topish — RELYQO');
  const title = document.querySelector('.consumerTitle');
  if (title) title.textContent = t('Какую организацию оценим?', 'Qaysi tashkilotni baholaymiz?');
  const hint = document.querySelector('.consumerHint');
  if (hint) hint.textContent = t('Найдите место, проверьте адрес и нажмите «Оценить в RELYQO».', 'Joyni toping, manzilini tekshiring va «RELYQO’da baholash»ni bosing.');
  const input = document.getElementById('catalogQuery');
  input.value = (params.get('q') || '').trim().slice(0,160);
  input.placeholder = t('Название организации или адрес', 'Tashkilot nomi yoki manzili');
  input.setAttribute('aria-label', t('Найти организацию', 'Tashkilot topish'));
  const actions = node('div','');actions.className='ratingDiscoveryActions';
  const here = node('button',t('Оценить рядом','Yaqin joyni baholash'),'discoveryHere');here.type='button';
  const byName = node('button',t('По названию','Nomi bo‘yicha'),'discoveryByName');byName.type='button';
  const nearby = document.getElementById('locate');nearby.textContent=t('Найти рядом','Yaqin joylarni topish');
  const mapButton = node('button',t('Выбрать на карте','Xaritadan tanlash'),'discoveryMap');mapButton.type='button';
  const qr = node('a',t('У меня есть QR','Menda QR bor'));qr.href='/rate?find=qr';
  actions.append(byName,nearby,mapButton,qr);
  const radiusControl=node('section','','currentRadiusControl');radiusControl.className='ratingRadiusControl';
  const radiusHeading=node('div','');radiusHeading.className='ratingRadiusHeading';
  const radiusLabel=node('strong',t('Радиус поиска','Qidiruv radiusi'),'currentRadiusLabel');
  radiusHeading.append(here,radiusLabel);
  const presets=node('div','');presets.className='ratingRadiusPresets';presets.setAttribute('role','group');presets.setAttribute('aria-labelledby','currentRadiusLabel');
  for(const meters of [300,500,1000,3000,5000]){
    const button=node('button',meters<1000?t(`${meters} м`,`${meters} m`):t(`${meters/1000} км`,`${meters/1000} km`));
    button.type='button';button.dataset.radius=String(meters);button.setAttribute('aria-pressed',String(meters===currentPlaceRadiusMeters));
    button.addEventListener('click',()=>{radiusInput.value=String(meters);applyRadius();});presets.append(button);
  }
  const radiusForm=node('form','');radiusForm.className='ratingRadiusForm';radiusForm.noValidate=true;
  const customLabel=node('label',t('Своё расстояние, м','O‘z masofangiz, m'));customLabel.htmlFor='currentRadiusMeters';
  const radiusInput=node('input','','currentRadiusMeters');radiusInput.type='text';radiusInput.inputMode='decimal';radiusInput.value=String(currentPlaceRadiusMeters);
  radiusInput.autocomplete='off';radiusInput.setAttribute('aria-describedby','currentRadiusHint currentRadiusError');
  const apply=node('button',t('Применить','Qo‘llash'));apply.type='submit';
  customLabel.append(radiusInput);radiusForm.append(customLabel,apply);
  const radiusHint=node('p',t('От 100 до 50 000 м. Своё расстояние: «Применить» или Enter.','100 dan 50 000 m gacha. O‘z masofangiz: «Qo‘llash» yoki Enter.'),'currentRadiusHint');
  const radiusError=node('p','','currentRadiusError');radiusError.setAttribute('role','alert');radiusError.hidden=true;
  radiusControl.append(radiusHeading,presets,radiusForm,radiusHint,radiusError);
  const panel = document.getElementById('directoryPanel');panel.append(radiusControl,actions);
  const status = document.getElementById('status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  panel.append(status,document.getElementById('error'));
  const currentPlace = node('section','','currentPlace');currentPlace.className='currentPlace hidden';
  currentPlace.setAttribute('aria-labelledby','currentPlaceTitle');
  const currentTitle = node('h2',t(`Организации в радиусе ${currentPlaceRadiusLabel()}`,`${currentPlaceRadiusLabel()} radiusdagi tashkilotlar`),'currentPlaceTitle');
  const currentMessage = node('p','','currentPlaceMessage');currentMessage.setAttribute('role','status');
  const candidates = node('div','','currentPlaceCandidates');
  const retry = node('button',t('Определить ещё раз','Qayta aniqlash'),'currentPlaceRetry');retry.type='button';
  currentPlace.append(currentTitle,currentMessage,candidates,retry);panel.after(currentPlace);
  const tools = node('div','');tools.className='ratingMapTools';
  tools.append(node('p',t('Передвиньте карту и нажмите «Искать в этой области». Нажмите на метку, чтобы выбрать организацию из списка.', 'Xaritani siljiting va «Shu hududdan izlash»ni bosing. Ro‘yxatdan tashkilot tanlash uchun belgisini bosing.')));
  const searchArea = node('button',t('Искать в этой области','Shu hududdan izlash'),'searchMapArea');searchArea.type='button';searchArea.disabled=!googleMap;tools.append(searchArea);
  document.getElementById('mapCard').append(tools);
  new MutationObserver(()=>{searchArea.disabled=!googleMap;}).observe(document.getElementById('map'),{attributes:true,attributeFilter:['class']});

  let operation = 0, findingHere = false, locating = false, savedScope = null;
  function validateRadius() {
    const raw=radiusInput.value.trim(),value=Number(raw.replace(',','.'));
    const valid=/^\d+(?:[.,]\d+)?$/.test(raw) && Number.isFinite(value) && value>=100 && value<=50000;
    window.relyqoCurrentRadiusInvalid=!valid;
    radiusInput.setAttribute('aria-invalid',String(!valid));radiusError.hidden=valid;
    radiusError.textContent=valid?'':t('Введите расстояние от 100 до 50 000 м.','100 dan 50 000 m gacha masofa kiriting.');
    return valid;
  }
  window.relyqoValidateCurrentRadius=validateRadius;
  function commitRadius() {
    if(!validateRadius())return false;
    currentPlaceRadiusMeters=Number(radiusInput.value.trim().replace(',','.'));
    for(const button of presets.children)button.setAttribute('aria-pressed',String(Number(button.dataset.radius)===currentPlaceRadiusMeters));
    currentTitle.textContent=t(`Организации в радиусе ${currentPlaceRadiusLabel()}`,`${currentPlaceRadiusLabel()} radiusdagi tashkilotlar`);
    return true;
  }
  async function applyRadius() {
    if(!commitRadius())return;
    if(!findingHere)return;
    document.getElementById('radius').value=String(currentPlaceRadiusMeters/1000);updateSearchScope();
    // Keep an outstanding GPS request; a known fix is reused for every radius change.
    if(currentCenter && locationFix)await refreshCatalog();
    else renderAll();
  }
  radiusInput.addEventListener('input',validateRadius);
  radiusInput.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();applyRadius();}});
  radiusForm.addEventListener('submit',event=>{event.preventDefault();applyRadius();});
  function choose(selected) {
    findingHere=selected===here;
    const controls=['radius','resultLimit','sortMode'].map(id=>document.getElementById(id));
    if(findingHere && !savedScope){
      savedScope=controls.map(control=>({value:control.value,disabled:control.disabled}));
      controls.forEach((control,index)=>{control.value=[String(currentPlaceRadiusMeters/1000),'20','distance'][index];control.disabled=true;});
    }else if(!findingHere && savedScope){
      controls.forEach((control,index)=>{control.value=savedScope[index].value;control.disabled=savedScope[index].disabled;});
      savedScope=null;
    }
    currentPlace.classList.toggle('hidden',!findingHere);
    document.body.classList.toggle('findingCurrentPlace',findingHere);
    updateSearchScope();
    for (const button of [here,byName,nearby,mapButton]) button.setAttribute('aria-pressed',String(button===selected));
  }
  function cancelPending() {
    ++locationRequestId; ++catalogRequestId; ++ratedRequestId;
    clearTimeout(ratedSearchTimer); clearTimeout(autoAdvisorTimer);
    window.relyqoCancelSearch?.();
    window.relyqoNearbyPending=false;
    window.relyqoNearbyState=null;
  }
  function nearMode() {
    showRatedOnly=false;showFavoritesOnly=false;
    document.getElementById('sortMode').value='distance';
    document.getElementById('serviceCategory').value='ALL';
    // Search near this point must not be hidden by a previously chosen name or rating threshold.
    input.value='';remoteSearchQuery='';remoteSearchIds=new Set();
    lastPartners=[];lastManualPlaces=[];lastExternalPlaces=[];
    renderAll();
  }
  async function byNameSearch() {
    const request=++operation;cancelPending();choose(byName);
    document.getElementById('sortMode').value='name';
    await reloadRatedCatalog();
    if(request===operation){status.textContent=t('Найдите организацию по названию или адресу.', 'Tashkilotni nomi yoki manzili bo‘yicha toping.');input.focus();}
  }
  async function findNearby() {
    const request=++operation;cancelPending();choose(nearby);nearMode();
    const success=await locate();
    if(request!==operation)return;
    if(!success){
      const message=document.getElementById('error').textContent;
      await reloadRatedCatalog();
      if(request!==operation)return;
      choose(byName);showError(message);
      status.textContent=t('Можно искать по названию или выбрать место на карте.', 'Nom bo‘yicha izlash yoki xaritadan joy tanlash mumkin.');
    }
  }
  window.relyqoRenderCurrentPlace = rows => {
    if(!findingHere)return;
    candidates.replaceChildren();
    const label=currentPlaceRadiusLabel();
    currentTitle.textContent=t(`Организации в радиусе ${label}`,`${label} radiusdagi tashkilotlar`);
    if(window.relyqoCurrentRadiusInvalid && !rows.length){currentMessage.textContent=t('Для поиска укажите радиус от 100 до 50 000 м.','Qidirish uchun 100 dan 50 000 m gacha radius kiriting.');return;}
    if(locating && !locationFix){currentMessage.textContent=t(`Разрешите доступ к местоположению для поиска организаций в радиусе ${label}…`,`${label} radiusdagi tashkilotlarni topish uchun joylashuvga ruxsat bering…`);return;}
    if(!currentCenter || !locationFix)return;
    const accuracy=locationFix.accuracy;
    const near=rows.filter(item=>item.country_code==='UZ' && hasMapLocation(item))
      .map(item=>({...item,meters:distanceKm(currentCenter,{lat:Number(item.latitude),lng:Number(item.longitude)})*1000}))
      .filter(item=>item.meters<=currentPlaceRadiusMeters+1e-6).sort((a,b)=>a.meters-b.meters);
    const selection=near;
    const state=window.relyqoNearbyState;
    const failed=state && (state.localFailed || state.googleFailed);
    const precision=accuracy===null?t('Точность местоположения неизвестна. ','Joylashuv aniqligi noma’lum. '):t(`Точность местоположения: около ${Math.ceil(accuracy)} м. `,`Joylashuv aniqligi: taxminan ${Math.ceil(accuracy)} m. `);
    const lowAccuracy=accuracy===null || accuracy>150
      ? t(`GPS неточный: поиск ограничен ${label} от определённой точки, радиус не расширяется. Проверьте адрес. `, `GPS noaniq: qidiruv aniqlangan nuqtadan ${label} bilan cheklangan, radius kengaytirilmaydi. Manzilni tekshiring. `) : '';
    currentMessage.textContent=precision+lowAccuracy+(selection.length
      ? t(`Выберите организацию в радиусе ${label}. Ближайшие показаны первыми.`, `${label} radiusdagi tashkilotni tanlang. Eng yaqinlari avval ko‘rsatilgan.`)
      : window.relyqoNearbyPending?t(`Ищем организации в пределах ${label}…`,`${label} ichida tashkilotlarni izlayapmiz…`)
        : failed?t(`Не удалось загрузить все источники в радиусе ${label}. Повторите поиск или найдите организацию по названию.`, `${label} radiusdagi barcha manbalarni yuklab bo‘lmadi. Qidiruvni takrorlang yoki tashkilotni nomi bo‘yicha toping.`)
          : t(`В доступных источниках в пределах ${label} ничего не найдено. Найдите организацию по названию или выберите место на карте.`, `Mavjud manbalarda ${label} ichida hech narsa topilmadi. Tashkilotni nomi bo‘yicha yoki xaritadan toping.`));
    for(const item of selection){
      const card=node('article','');card.className='currentPlaceCandidate';
      const name=node('h3',item.title);name.setAttribute('data-user-content','');
      const address=node('p',item.address||t('Адрес не указан','Manzil ko‘rsatilmagan'));address.setAttribute('data-user-content','');
      const distance=node('small',t(`Примерно ${Math.max(1,Math.round(item.meters))} м от вас`,`Sizdan taxminan ${Math.max(1,Math.round(item.meters))} m`));
      const select=node(item.kind==='external'?'button':'a',t('Я здесь — оценить','Men shu yerdaman — baholash'));select.className='currentPlaceSelect';
      if(item.kind==='external'){select.type='button';select.addEventListener('click',()=>openManualDialog(item,'rate'));}
      else select.href=ratingUrl(item);
      card.append(name,address,distance);
      if(item.kind==='external'){
        const attribution=node('div','Google Maps');attribution.setAttribute('translate','no');
        if(item.google_details && window.relyqoGoogleRating)window.relyqoGoogleRating.render(attribution,item.google_details,true);
        card.append(attribution);
      }
      card.append(select);candidates.append(card);
    }
    const note=node('p',t('Google показывает до 20 мест; список может быть неполным. Подтверждённое посещение — по одноразовому QR.', 'Google 20 tagacha joy ko‘rsatadi; ro‘yxat to‘liq bo‘lmasligi mumkin. Tasdiqlangan tashrif — bir martalik QR orqali.'));note.className='currentPlaceNote';candidates.append(note);
  };
  async function findHere() {
    if(!commitRadius())return;
    const request=++operation;cancelPending();choose(here);locating=true;
    // Fresh coordinates keep the chosen radius, independently of ordinary map settings.
    locationFix=null;currentCenter=null;nearMode();here.disabled=true;retry.disabled=true;
    const success=await locate({fresh:true});
    if(request!==operation){here.disabled=false;retry.disabled=false;return;}
    locating=false;here.disabled=false;retry.disabled=false;
    if(success)renderAll();
    else{
      const message=document.getElementById('error').textContent;
      choose(byName);
      await reloadRatedCatalog();
      if(request!==operation)return;
      showError(message);
      status.textContent=t('Можно искать по названию или выбрать место на карте.', 'Nom bo‘yicha izlash yoki xaritadan joy tanlash mumkin.');
    }
  }
  async function chooseMap() {
    const request=++operation;cancelPending();choose(mapButton);
    status.textContent=t('Открываем карту…','Xarita ochilmoqda…');
    const data=await window.relyqoLocationsReady;
    if(request!==operation)return;
    const cities=data?.cities || window.relyqoUzbekistan?.cities || [];
    const region=ratedFilterValue('#ratedRegion'),city=ratedFilterValue('#ratedCity');
    const selected=cities.find(c=>c.city===city && (region==='ALL'||c.region_code===region))
      || (region!=='ALL'?cities.filter(c=>c.region_code===region).sort((a,b)=>(b.population||0)-(a.population||0))[0]:null)
      || cities.find(c=>c.city==='Tashkent');
    currentCenter=selected?{lat:selected.latitude,lng:selected.longitude}:{lat:41.3111,lng:69.2797};
    centerLabel=t('Центр поиска','Qidiruv markazi');
    nearMode();
    try {await refreshCatalog();} catch(error){if(request===operation)showError(error.message);}
    if(request===operation){searchArea.disabled=!googleMap;document.getElementById('mapCard').scrollIntoView({behavior:'smooth',block:'start'});}
  }
  async function findInMapArea() {
    const point=googleMap?.getCenter();
    if(!point)return;
    const lat=point.lat(),lng=point.lng();
    if(!Number.isFinite(lat)||!Number.isFinite(lng)||lat<35||lat>46||lng<55||lng>74){showError(t('Выберите область карты в Узбекистане.', 'Xaritadan O‘zbekistondagi hududni tanlang.'));return;}
    const request=++operation;cancelPending();choose(mapButton);
    currentCenter={lat,lng};centerLabel=t('Центр поиска','Qidiruv markazi');
    nearMode();searchArea.disabled=true;
    try{await refreshCatalog();}catch(error){if(request===operation)showError(error.message);}
    finally{if(request===operation)searchArea.disabled=!googleMap;}
  }
  nearby.removeEventListener('click',locate);
  here.addEventListener('click',findHere);retry.addEventListener('click',findHere);
  nearby.addEventListener('click',findNearby);byName.addEventListener('click',byNameSearch);
  mapButton.addEventListener('click',chooseMap);searchArea.addEventListener('click',findInMapArea);
  // City and typed searches supersede a pending permission dialog or map opening.
  for(const id of ['ratedRegion','ratedCity','ratedCategory','catalogSearchButton'])document.getElementById(id).addEventListener(id==='catalogSearchButton'?'click':'change',()=>{if(!window.relyqoRestoringLocation){++operation;choose(byName);}});
  input.addEventListener('keydown',event=>{if(event.key==='Enter')++operation;});
  input.addEventListener('input',()=>{
    ++operation;++locationRequestId;
    if(!showRatedOnly){
      ++catalogRequestId;showRatedOnly=true;choose(byName);updateCatalogMode();scheduleRatedReload();
    }
  });
  const initial=operation;
  Promise.resolve(window.relyqoLocationsReady).then(()=>{
    if(operation!==initial)return;
    if(mode==='here')return findHere();
    if(mode==='nearby')return findNearby();
    if(mode==='map')return chooseMap();
    return byNameSearch();
  });
})();
