/* Rating entrance reuses the live search and map; no coordinates enter the URL or storage. */
(() => {
  const params = new URLSearchParams(location.search);
  const mode = params.get('find') || (['/rate','/consumer'].includes(location.pathname) ? 'search' : null);
  if (!['here','search','nearby','map'].includes(mode) || !document.getElementById('directoryPanel')) return;
  if (document.body.classList.contains('ratingDiscovery')) return;
  document.body.classList.add('ratingDiscovery');
  const t = (ru, uz) => document.documentElement.lang === 'uz' ? uz : ru;
  const node = (tag, text, id) => {const n=document.createElement(tag);n.textContent=text;if(id)n.id=id;return n;};
  document.title = t('Найти организацию для оценки — RELYQO', 'Baholash uchun tashkilot topish — RELYQO');
  const title = document.querySelector('.consumerTitle');
  if (title) title.textContent = t('Какую организацию оценим?', 'Qaysi tashkilotni baholaymiz?');
  const hint = document.querySelector('.consumerHint');
  if (hint) hint.textContent = t('Найдите организацию и нажмите «Оценить».', 'Tashkilotni toping va «Baholash»ni bosing.');
  const input = document.getElementById('catalogQuery');
  input.value = (params.get('q') || '').trim().slice(0,160);
  input.placeholder = t('Название организации или адрес', 'Tashkilot nomi yoki manzili');
  input.setAttribute('aria-label', t('Найти организацию', 'Tashkilot topish'));
  const actions = node('div','');actions.className='ratingDiscoveryActions';
  const here = node('button',t('Рядом со мной','Yaqinimda'),'discoveryHere');here.type='button';
  const byName = node('button',t('По списку','Ro‘yxatdan'),'discoveryByName');byName.type='button';
  const qr = node('a',t('Оценить по QR','QR orqali baholash'));qr.href='/rate?find=qr';qr.className='ratingQr';
  actions.append(here,byName);
  const radiusControl=node('details','','currentRadiusControl');radiusControl.className='ratingRadiusControl';radiusControl.hidden=true;
  const radiusSummary=node('summary','','currentRadiusSummary');
  const radiusLabel=node('strong',t('Радиус поиска','Qidiruv radiusi'),'currentRadiusLabel');
  radiusLabel.className='srOnly';
  radiusControl.append(radiusSummary,radiusLabel);
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
  radiusControl.append(presets,radiusForm,radiusHint,radiusError);
  const panel = document.getElementById('directoryPanel');
  const sectorField=node('label',t('Сфера','Soha'));sectorField.className='discoverySector';sectorField.setAttribute('for','discoveryCategory');
  const sector=node('select','','discoveryCategory');sector.setAttribute('aria-label',t('Сфера','Soha'));
  for(const [code,ru,uz] of [
    ['ALL','Все сферы','Barcha sohalar'],['FOOD','Рестораны и кафе','Restoran va kafelar'],
    ['EDUCATION','Образование','Ta’lim'],['HEALTH','Здоровье','Sog‘liq'],
    ['BEAUTY','Красота и уход','Go‘zallik va parvarish'],['RETAIL','Магазины','Do‘konlar'],
    ['AUTO_SERVICE','Автоуслуги','Avtoxizmatlar'],['HOTEL','Гостиницы','Mehmonxonalar'],
    ['ENTERTAINMENT','Развлечения','Ko‘ngilochar xizmatlar'],
    ['PROFESSIONAL_SERVICE','Профессиональные услуги','Professional xizmatlar'],['OTHER','Другие услуги','Boshqa xizmatlar'],
  ]){const option=node('option',t(ru,uz));option.value=code;sector.append(option);}
  sector.value='ALL';sectorField.append(sector);
  const filters=node('div','');filters.className='discoveryFilters';filters.append(sectorField,radiusControl);
  panel.querySelector('.catalogSearchWrap').before(actions);panel.querySelector('.catalogSearchWrap').after(filters);
  const addPlace = document.getElementById('addPlace');
  addPlace.textContent = t('Не нашли организацию? Добавить организацию', 'Tashkilotni topmadingizmi? Tashkilot qo‘shish');
  addPlace.classList.add('ratingAddPlace');
  addPlace.hidden = false;
  document.getElementById('listCard').after(addPlace,qr);
  const status = document.getElementById('status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const locationNotice=node('p','','discoveryLocationNotice');locationNotice.className='discoveryLocationNotice';locationNotice.hidden=true;
  locationNotice.setAttribute('role','status');locationNotice.setAttribute('aria-live','polite');
  panel.append(locationNotice,status,document.getElementById('error'));
  const currentPlace = node('section','','currentPlace');currentPlace.className='currentPlace hidden';
  currentPlace.setAttribute('aria-labelledby','currentPlaceTitle');
  const currentTitle = node('h2',t(`Организации в радиусе ${currentPlaceRadiusLabel()}`,`${currentPlaceRadiusLabel()} radiusdagi tashkilotlar`),'currentPlaceTitle');
  const currentMessage = node('p','','currentPlaceMessage');currentMessage.setAttribute('role','status');
  const candidates = node('div','','currentPlaceCandidates');
  const retry = node('button',t('Определить ещё раз','Qayta aniqlash'),'currentPlaceRetry');retry.type='button';
  currentPlace.append(currentTitle,currentMessage,retry);
  const results=document.getElementById('results');results.before(currentPlace,candidates);candidates.append(results);

  let operation = 0, findingHere = false, savedScope = null;
  function clearLocationNotice() {locationNotice.hidden=true;locationNotice.textContent='';window.relyqoLocationError='';}
  function locationProblem(message) {window.relyqoLocationError=message;locationNotice.textContent=message;locationNotice.hidden=!message;}
  window.relyqoLocationUsable=()=>{
    if(!locationFix)return false;
    const valid=locationFix.source==='manual' || (Number.isFinite(locationFix.accuracy) && locationFix.accuracy>0 && locationFix.accuracy<=Math.min(100,currentPlaceRadiusMeters/2));
    if(!valid)locationProblem(t('Точности местоположения недостаточно для этого радиуса. Укажите точку на карте или включите точную геолокацию и повторите поиск.','Joylashuv aniqligi bu radius uchun yetarli emas. Xaritada nuqta tanlang yoki aniq joylashuvni yoqib, qayta urinib ko‘ring.'));
    else clearLocationNotice();
    return valid;
  };
  const originPicker=window.relyqoSearchOrigin({parent:currentPlace,toggleParent:panel,loadMaps:loadGooglePlaces,getCenter:()=>currentCenter,getRadius:()=>currentPlaceRadiusMeters,onOpen:()=>{
    ++operation;++locationRequestId;here.disabled=false;retry.disabled=false;
    if(!findingHere){cancelPending();choose(here);currentCenter=null;locationFix=null;nearMode();}
    if(!locationFix)locationProblem(t('Укажите точку на карте, чтобы искать в выбранном радиусе.','Tanlangan radiusda qidirish uchun xaritada nuqta belgilang.'));
    renderAll();
  },onSelect:async point=>{
    if(!findingHere || !commitRadius())return;
    ++operation;cancelPending();clearLocationNotice();clearError();
    currentCenter=point;locationFix={source:'manual',accuracy:null};
    showRatedOnly=false;here.disabled=false;retry.disabled=false;
    centerLabel=t('Выбранная точка','Tanlangan nuqta');
    await refreshCatalog();
  }});
  function syncSector() {
    document.getElementById('serviceCategory').value=sector.value;
    document.getElementById('ratedCategory').value=sector.value;
  }
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
    originPicker.updateRadius();
    for(const button of presets.children)button.setAttribute('aria-pressed',String(Number(button.dataset.radius)===currentPlaceRadiusMeters));
    currentTitle.textContent=t(`Организации в радиусе ${currentPlaceRadiusLabel()}`,`${currentPlaceRadiusLabel()} radiusdagi tashkilotlar`);
    radiusSummary.textContent=t(`Расстояние: ${currentPlaceRadiusLabel()}`,`Masofa: ${currentPlaceRadiusLabel()}`);
    return true;
  }
  async function applyRadius() {
    if(!commitRadius())return;
    if(!findingHere)return;
    document.getElementById('radius').value=String(currentPlaceRadiusMeters/1000);updateSearchScope();
    // Keep an outstanding GPS request; a known fix is reused for every radius change.
    if(currentCenter && locationFix){++catalogRequestId;window.relyqoNearbyPending=false;await refreshCatalog();}
    else renderAll();
  }
  radiusInput.addEventListener('input',validateRadius);
  radiusInput.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();applyRadius();}});
  radiusForm.addEventListener('submit',event=>{event.preventDefault();applyRadius();});
  function choose(selected) {
    findingHere=selected===here;
    syncSector();
    clearLocationNotice();
    if(!findingHere){here.disabled=false;retry.disabled=false;originPicker.close();}
    const controls=['radius','resultLimit','sortMode'].map(id=>document.getElementById(id));
    if(findingHere && !savedScope){
      savedScope=controls.map(control=>({value:control.value,disabled:control.disabled}));
      controls.forEach((control,index)=>{control.value=[String(currentPlaceRadiusMeters/1000),'20','distance'][index];control.disabled=true;});
    }else if(!findingHere && savedScope){
      controls.forEach((control,index)=>{control.value=savedScope[index].value;control.disabled=savedScope[index].disabled;});
      savedScope=null;
    }
    currentPlace.classList.toggle('hidden',!findingHere);
    radiusControl.hidden=!findingHere;
    if(!findingHere)radiusControl.open=false;
    document.body.classList.toggle('findingCurrentPlace',findingHere);
    updateSearchScope();
    for (const button of [here,byName]) button.setAttribute('aria-pressed',String(button===selected));
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
    syncSector();
    // Preserve the name query while dropping results from the previous origin.
    remoteSearchQuery='';remoteSearchIds=new Set();
    lastPartners=[];lastManualPlaces=[];lastExternalPlaces=[];
    renderAll();
  }
  function resetListFilters() {
    document.getElementById('sortMode').value='name';
    showFavoritesOnly=false;
    for(const id of ['ratedRegion','ratedCity','ratedScoreType'])document.getElementById(id).value='ALL';
    syncSector();
    document.getElementById('ratedMinScore').value='0';
  }
  async function byNameSearch() {
    const request=++operation;cancelPending();choose(byName);clearError();resetListFilters();
    await reloadRatedCatalog();
    if(request===operation)status.textContent='';
  }
  let nearbyQueryTimer;
  window.relyqoRatingSearch=async()=>{
    if(!findingHere)return byNameSearch();
    clearTimeout(nearbyQueryTimer);
    if(here.disabled)return;
    if(currentCenter && locationFix)return refreshCatalog();
    return findHere();
  };
  sector.addEventListener('change',async()=>{
    syncSector();clearError();
    if(!findingHere){await byNameSearch();return;}
    // Changing the sector preserves the radius and an outstanding GPS request.
    if(currentCenter && locationFix)await refreshCatalog();
    else renderAll();
  });
  window.relyqoRenderCurrentPlace = rows => {
    if(!findingHere)return;
    const label=currentPlaceRadiusLabel();
    currentTitle.textContent=t(`Организации в радиусе ${label}`,`${label} radiusdagi tashkilotlar`);
    // Distances are straight-line measurements from the accepted search origin.
    const accuracy=locationFix?.accuracy;
    currentMessage.textContent=locationFix?.source==='manual'
      ? t(`Радиус ${label} от выбранной точки, по прямой.`, `Tanlangan nuqtadan to‘g‘ri chiziq bo‘ylab ${label} radius.`)
      : locationFix && window.relyqoLocationUsable()
        ? t(`Радиус ${label} по прямой. Точность местоположения: ±${Math.ceil(accuracy)} м.`, `To‘g‘ri chiziq bo‘ylab ${label} radius. Joylashuv aniqligi: ±${Math.ceil(accuracy)} m.`) : '';
  };
  // One list for both modes; rating is the only primary action on each place.
  window.relyqoRenderRatingRows = rows => {
    const root=document.getElementById('results');root.replaceChildren();
    for(const item of rows){
      const card=node('article','');card.className='place currentPlaceCandidate';card.id=markerCardId(item);
      const name=node('h3','');name.setAttribute('data-user-content','');
      if(item.kind==='external')name.textContent=item.title;
      else {const detail=node('a',item.title);detail.href=profileUrl(item);detail.className='placeDetailsLink';name.append(detail);}
      const address=node('p',item.address||t('Адрес не указан','Manzil ko‘rsatilmagan'));address.setAttribute('data-user-content','');
      const meters=Math.max(1,Math.round(item.distance*1000));
      const distance=node('small',locationFix?.source==='manual' ? t(`Примерно ${meters} м от выбранной точки`,`Tanlangan nuqtadan taxminan ${meters} m`) : t(`Примерно ${meters} м от вас`,`Sizdan taxminan ${meters} m`));
      const select=node(item.kind==='external'?'button':'a',t('Оценить','Baholash'));select.className='currentPlaceSelect rateLink';
      if(item.kind==='external'){select.type='button';select.addEventListener('click',()=>openManualDialog(item,'rate'));}
      else select.href=ratingUrl(item);
      card.append(name,address);
      if(findingHere && item.distance!=null && Number.isFinite(item.distance))card.append(distance);
      if(item.kind==='external'){
        const attribution=node('div','Google Maps');attribution.setAttribute('translate','no');
        if(item.google_details && window.relyqoGoogleRating)window.relyqoGoogleRating.render(attribution,item.google_details,true);
        card.append(attribution);
      }
      card.append(select);root.append(card);
    }
    if(rows.some(item=>item.kind==='external')){const note=node('p',t('Google показывает до 20 мест; список может быть неполным.','Google 20 tagacha joy ko‘rsatadi; ro‘yxat to‘liq bo‘lmasligi mumkin.'));note.className='currentPlaceNote';root.append(note);}
    document.getElementById('listCount').textContent=t(`${rows.length} найдено`,`${rows.length} ta topildi`);
  };
  async function findHere() {
    if(!commitRadius()){radiusControl.hidden=false;radiusControl.open=true;return;}
    const request=++operation;cancelPending();choose(here);
    originPicker.close();
    // Fresh coordinates keep the chosen radius, independently of ordinary map settings.
    locationFix=null;currentCenter=null;nearMode();here.disabled=true;retry.disabled=true;
    let locationError='';
    const success=await locate({fresh:true,onLocationError:message=>{locationError=message;}});
    if(request!==operation)return;
    here.disabled=false;retry.disabled=false;
    if(success)renderAll();
    else{
      locationProblem(locationError);
      status.textContent='';
      renderAll();
    }
  }
  here.addEventListener('click',findHere);retry.addEventListener('click',findHere);
  byName.addEventListener('click',byNameSearch);
  // Explicit list filters supersede a pending location request or map opening.
  for(const id of ['ratedRegion','ratedCity','ratedCategory'])document.getElementById(id).addEventListener('change',()=>{if(!window.relyqoRestoringLocation){++operation;choose(byName);}});
  input.addEventListener('input',()=>{
    if(findingHere){
      ++catalogRequestId;window.relyqoNearbyPending=false;
      clearTimeout(nearbyQueryTimer);renderAll();
      if(currentCenter && locationFix)nearbyQueryTimer=setTimeout(()=>{if(findingHere)refreshCatalog();},250);
      return;
    }
    ++operation;++locationRequestId;
    choose(byName);clearError();
    if(!showRatedOnly){
      ++catalogRequestId;showRatedOnly=true;updateCatalogMode();scheduleRatedReload();
    }
  });
  commitRadius();choose(byName);
  // The advanced catalog retains these controls on /nearby only.
  for(const selector of ['.consumerPlace','.consumerChips','.searchSource','#citySearchStatus','.consumerSecondary','.catalogOptions','.searchAdvanced','.advisorDetails','#locate','#mapCard','#status']){
    for(const element of document.querySelectorAll(selector))element.hidden=true;
  }
  const initial=operation;
  Promise.resolve(window.relyqoLocationsReady).then(()=>{
    if(operation!==initial)return;
    if(mode==='here'||mode==='nearby')return findHere();
    if(mode==='map')return originPicker.open();
    return byNameSearch();
  });
})();


