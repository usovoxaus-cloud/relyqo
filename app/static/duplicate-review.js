(() => {
  const root=document.getElementById('organizationDirectory');if(!root)return;
  const t=(ru,uz)=>document.documentElement.lang==='uz'?uz:ru;
  const button=document.createElement('button');button.type='button';button.className='btn secondary';button.id='reviewDuplicates';button.textContent=t('Проверить похожие карточки','O‘xshash sahifalarni tekshirish');
  const output=document.createElement('section');output.id='duplicateReview';output.hidden=true;root.before(button,output);
  const node=(tag,text,authored=false)=>{const el=document.createElement(tag);el.textContent=text;if(authored)el.setAttribute('data-user-content','');return el;};
  button.addEventListener('click',async()=>{
    button.disabled=true;output.hidden=false;output.replaceChildren(node('p',t('Проверяем карточки…','Sahifalar tekshirilmoqda…')));
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
    try{
      const response=await fetch('/v1/admin/duplicate-places?'+new URLSearchParams({q:document.getElementById('directoryQuery').value.trim().slice(0,120)}),{cache:'no-store',signal:controller.signal});
      if(!response.ok)throw Error();const data=await response.json();output.replaceChildren();
      output.append(node('p',t('Это возможные совпадения. Сверьте филиал, адрес и источник: одинаковое название ещё не означает одну организацию. Оценки и доступы не изменены.','Bular ehtimoliy mosliklar. Filial, manzil va manbani tekshiring: bir xil nom bir tashkilot degani emas. Baholar va kirish huquqlari o‘zgarmadi.')));
      if(!data.groups.length)output.append(node('p',t('Похожих карточек не найдено.','O‘xshash sahifalar topilmadi.')));
      for(const group of data.groups){
        const card=node('article','');card.className='appCard';
        card.append(node('strong',group.same_google_id?t('Одинаковый объект Google Maps','Bir xil Google Maps obyekti'):group.same_address?t('Совпадают название и адрес','Nom va manzil bir xil'):t('Похожее название, проверьте адреса','O‘xshash nom, manzillarni tekshiring')));
        for(const item of group.items){const p=node('p',''),link=node('a',item.name+' · '+item.address,true);link.href='/place?'+new URLSearchParams({object_key:item.object_key});p.append(link,node('span',' · Community: '+item.community_count));card.append(p);}
        output.append(card);
      }
      if(data.truncated)output.append(node('p',t('Список ограничен. Уточните название в поиске.','Ro‘yxat cheklangan. Qidiruvda nomni aniqlashtiring.')));
    }catch{output.replaceChildren(node('p',t('Не удалось проверить карточки. Повторите попытку.','Sahifalarni tekshirib bo‘lmadi. Qayta urinib ko‘ring.')));}
    finally{clearTimeout(timer);button.disabled=false;}
  });
})();
