(() => {
  const name=document.getElementById('manualName'),address=document.getElementById('manualAddress');
  if(!name||!address)return;
  const t=(ru,uz)=>document.documentElement.lang==='uz'?uz:ru;
  const box=document.createElement('section');box.id='existingPlaceCandidates';box.hidden=true;box.setAttribute('aria-live','polite');
  name.closest('label').before(box);
  let generation=0,timer,controller;
  async function find(){
    const query=name.value.trim(),id=++generation;controller?.abort();box.replaceChildren();box.hidden=true;
    if(query.length<2)return;
    controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),8000);
    try{
      const response=await fetch('/v1/public/rated-organizations?'+new URLSearchParams({q:query.slice(0,120),include_unrated:'true',limit:'5',sort:'name'}),{cache:'no-store',signal:controller.signal});
      if(!response.ok)return;const data=await response.json();if(id!==generation||!data.items?.length)return;
      const title=document.createElement('h3');title.textContent=t('Похожие организации уже есть','O‘xshash tashkilotlar allaqachon bor');
      const hint=document.createElement('p');hint.textContent=t('Проверьте адрес. Если это нужная организация, откройте её карточку. Если другая — продолжите добавление.','Manzilni tekshiring. Kerakli tashkilot bo‘lsa, uning sahifasini oching. Boshqa bo‘lsa, qo‘shishni davom ettiring.');box.append(title,hint);
      for(const item of data.items){
        const key=item.object_key||(item.kind==='partner'?'relyqo:'+item.branch_id:'manual:'+item.id);
        if(!/^(manual|relyqo):[a-zA-Z0-9-]+$/.test(key))continue;
        const link=document.createElement('a');link.href='/place?'+new URLSearchParams({object_key:key});link.textContent=(item.name||item.organization)+' · '+(item.address||'');link.setAttribute('data-user-content','');
        const row=document.createElement('p');row.append(link);box.append(row);
      }
      box.hidden=false;
    }catch{}finally{clearTimeout(timeout);}
  }
  window.relyqoSuggestExisting=find;
  name.addEventListener('input',()=>{++generation;controller?.abort();clearTimeout(timer);timer=setTimeout(find,350);});
  document.getElementById('manualDialog').addEventListener('close',()=>{++generation;controller?.abort();clearTimeout(timer);box.hidden=true;});
})();
