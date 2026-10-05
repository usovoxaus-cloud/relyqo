/* A visitor-selected search origin is ephemeral and never creates an organization. */
window.relyqoSearchOrigin = ({parent, loadMaps, getCenter, getRadius, onSelect}) => {
  const t=(ru,uz)=>document.documentElement.lang==='uz'?uz:ru;
  const node=(tag,id,text='')=>{const el=document.createElement(tag);el.id=id;el.textContent=text;return el;};
  const toggle=node('button','searchOriginToggle',t('Указать точку на карте','Xaritada nuqta tanlash'));toggle.type='button';
  const panel=node('section','searchOriginPanel');panel.hidden=true;panel.className='searchOriginPanel';
  toggle.setAttribute('aria-controls',panel.id);toggle.setAttribute('aria-expanded','false');
  const instructions=node('p','searchOriginHint',t('Найдите адрес или нажмите на карту. Подтвердите центр круга поиска.','Manzilni toping yoki xaritani bosing. Qidiruv doirasi markazini tasdiqlang.'));
  const form=node('form','searchOriginForm'),input=node('input','searchOriginAddress');
  input.type='search';input.placeholder=t('Город и адрес','Shahar va manzil');input.setAttribute('aria-label',input.placeholder);
  const search=node('button','searchOriginSearch',t('Найти адрес','Manzilni topish'));search.type='submit';form.append(input,search);
  const status=node('p','searchOriginStatus');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const choices=node('div','searchOriginChoices');
  const root=node('div','searchOriginMap');root.className='searchOriginMap';root.hidden=true;root.setAttribute('aria-label',t('Центр и радиус поиска','Qidiruv markazi va radiusi'));
  const confirm=node('button','searchOriginConfirm',t('Искать вокруг этой точки','Shu nuqta atrofida qidirish'));confirm.type='button';confirm.disabled=true;
  panel.append(instructions,form,status,choices,root,confirm);parent.append(toggle,panel);
  let map,marker,circle,draft=null,revision=0;
  const valid=p=>p && Number.isFinite(p.lat) && Number.isFinite(p.lng) && Math.abs(p.lat)<=90 && Math.abs(p.lng)<=180;
  const deadline=promise=>new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error('Map timeout')),15000);
    Promise.resolve(promise).then(resolve,reject).finally(()=>clearTimeout(timer));
  });
  function close(){++revision;panel.hidden=true;toggle.setAttribute('aria-expanded','false');search.disabled=false;}
  function updateRadius(){circle?.setRadius(getRadius());}
  function select(point){
    if(panel.hidden || !valid(point))return;
    draft={...point};confirm.disabled=false;
    if(!marker){
      marker=new google.maps.Marker({map,position:draft,draggable:true,title:t('Центр поиска','Qidiruv markazi')});
      marker.addListener('dragend',event=>{if(event.latLng){++revision;search.disabled=false;select({lat:event.latLng.lat(),lng:event.latLng.lng()});}});
      circle=new google.maps.Circle({map,center:draft,radius:getRadius(),clickable:false,strokeColor:'#178463',strokeWeight:2,fillColor:'#78e3c0',fillOpacity:.22});
    }else{marker.setPosition(draft);marker.setMap(map);circle.setCenter(draft);circle.setMap(map);updateRadius();}
    map.setCenter(draft);map.setZoom(getRadius()<=500?16:getRadius()<=2000?14:getRadius()<=5000?13:10);
    status.textContent=t('Проверьте точку и нажмите «Искать вокруг этой точки».','Nuqtani tekshiring va «Shu nuqta atrofida qidirish»ni bosing.');
  }
  async function show(request){
    if(!map){
      if(!await deadline(loadMaps()) || request!==revision)return false;
      await deadline(google.maps.importLibrary('maps'));
      if(request!==revision)return false;
      root.hidden=false;
      // The overview is only a viewport. It cannot be submitted as a location.
      map=new google.maps.Map(root,{center:getCenter()||{lat:41.31,lng:69.28},zoom:getCenter()?15:11,mapTypeControl:false,streetViewControl:false,fullscreenControl:false,gestureHandling:'cooperative'});
      map.addListener('click',event=>{if(event.latLng){++revision;search.disabled=false;select({lat:event.latLng.lat(),lng:event.latLng.lng()});}});
    }
    return request===revision;
  }
  const unavailable=()=>{status.textContent=t('Карта недоступна. Повторите попытку или выберите «По списку».','Xarita mavjud emas. Qayta urinib ko‘ring yoki «Ro‘yxatdan»ni tanlang.');};
  toggle.addEventListener('click',async()=>{
    if(!panel.hidden){close();return;}
    panel.hidden=false;toggle.setAttribute('aria-expanded','true');
    const request=++revision;draft=null;confirm.disabled=true;marker?.setMap(null);circle?.setMap(null);choices.replaceChildren();
    status.textContent=t('Открываем карту…','Xarita ochilmoqda…');
    try{if(!await show(request))throw Error('Map unavailable');if(request===revision)status.textContent=instructions.textContent;}
    catch{if(request===revision)unavailable();}
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();const query=input.value.trim();if(query.length<3)return;
    const request=++revision;search.disabled=true;choices.replaceChildren();confirm.disabled=true;draft=null;marker?.setMap(null);circle?.setMap(null);
    status.textContent=t('Ищем адрес…','Manzil qidirilmoqda…');
    try{
      if(!await show(request))throw Error('Map unavailable');
      const {Place}=await deadline(google.maps.importLibrary('places'));
      if(request!==revision)return;
      const {places}=await deadline(Place.searchByText({textQuery:query,fields:['displayName','formattedAddress','location','addressComponents'],region:'uz',language:document.documentElement.lang==='uz'?'uz':'ru',maxResultCount:5}));
      if(request!==revision)return;
      for(const place of places||[]){
        if(!place.location || !(place.addressComponents||[]).some(part=>(part.types||[]).includes('country')&&part.shortText==='UZ'))continue;
        const point={lat:place.location.lat(),lng:place.location.lng()};if(!valid(point))continue;
        const button=node('button','',[place.displayName,place.formattedAddress].filter(Boolean).join(' · '));button.type='button';button.setAttribute('data-user-content','');
        button.addEventListener('click',()=>{++revision;select(point);});choices.append(button);
      }
      status.textContent=choices.children.length?t('Выберите адрес и проверьте точку на карте.','Manzilni tanlang va xaritadagi nuqtani tekshiring.'):t('Адрес не найден. Уточните запрос или нажмите на карту.','Manzil topilmadi. So‘rovni aniqlashtiring yoki xaritani bosing.');
    }catch{if(request===revision)unavailable();}
    finally{if(request===revision)search.disabled=false;}
  });
  input.addEventListener('input',()=>{++revision;search.disabled=false;choices.replaceChildren();draft=null;confirm.disabled=true;marker?.setMap(null);circle?.setMap(null);});
  confirm.addEventListener('click',()=>{if(panel.hidden || !valid(draft))return;const point={...draft};close();onSelect(point);});
  return {close,updateRadius};
};
