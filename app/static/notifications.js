(() => {
  'use strict';
  const $=id=>document.getElementById(id),t=(ru,uz)=>document.documentElement.lang==='uz'?uz:ru;
  let busy=false;
  async function api(body){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
    try {
      const response=await fetch('/v1/notifications/preferences',{credentials:'same-origin',cache:'no-store',signal:controller.signal,
        ...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
      if(response.status===401){$('notificationLogin').hidden=false;throw Error(t('Войдите, чтобы настроить уведомления.','Bildirishnomalarni sozlash uchun hisobingizga kiring.'));}
      if(!response.ok)throw Error(t('Не удалось сохранить настройки. Проверьте подтверждение почты и повторите.','Sozlamalar saqlanmadi. Email tasdiqlanganini tekshirib, qayta urinib ko‘ring.'));
      return await response.json();
    }catch(error){if(error.name==='AbortError'||error instanceof TypeError)throw Error(t('Нет связи с сервером. Повторите попытку.','Server bilan aloqa yo‘q. Qayta urinib ko‘ring.'));throw error;}
    finally{clearTimeout(timer);}
  }
  function render(data){
    $('notificationConsent').checked=data.enabled;
    // Disabling remains available even when the sender or verified address changes.
    $('notificationForm').hidden=false;
    $('notificationVerify').hidden=data.verified;
    $('notificationStatus').textContent=!data.verified?t('Сначала подтвердите почту в настройках аккаунта.','Avval hisob sozlamalarida emailni tasdiqlang.'):
      !data.available?t('Отправка писем пока недоступна. Уведомления внутри сайта продолжают работать.','Email yuborish hozircha mavjud emas. Sayt ichidagi bildirishnomalar ishlashda davom etadi.'):
      (data.enabled?t('Включено для: ','Yoqilgan: '):t('Выключено. Подтверждённый адрес: ','O‘chirilgan. Tasdiqlangan email: '))+data.email;
  }
  $('notificationForm').addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;busy=true;$('notificationSave').disabled=true;$('notificationConsent').disabled=true;$('notificationError').hidden=true;$('notificationSaved').textContent='';
    try {const enabled=$('notificationConsent').checked;render(await api({enabled,consent:enabled}));$('notificationSaved').textContent=t('Настройки сохранены.','Sozlamalar saqlandi.');}
    catch(error){$('notificationError').textContent=error.message;$('notificationError').hidden=false;}
    finally{busy=false;$('notificationSave').disabled=false;$('notificationConsent').disabled=false;}
  });
  Promise.resolve(window.relyqoLanguageReady).then(async()=>{
    $('notificationTitle').textContent=t('Уведомления по email','Email bildirishnomalari');document.title=$('notificationTitle').textContent+' — RELYQO';
    $('notificationIntro').textContent=t('Получайте уведомления о новых сообщениях и изменениях обращений, даже когда сайт закрыт. Текст переписки, оценки и фотографии в письма не включаются.','Sayt yopiq bo‘lsa ham murojaatlardagi yangi xabarlar va o‘zgarishlardan xabardor bo‘ling. Xatlarda yozishmalar, baholar va suratlar bo‘lmaydi.');
    $('notificationConsentLabel').textContent=t('Хочу получать уведомления об обращениях на подтверждённую почту. Могу отключить их здесь в любое время.','Murojaatlar haqidagi bildirishnomalarni tasdiqlangan emailga olishni xohlayman. Ularni shu yerda istalgan vaqt o‘chirishim mumkin.');
    $('notificationSignIn').textContent=t('Войти','Kirish');$('notificationBusinessSignIn').textContent=t('Вход для владельца бизнеса','Biznes egasi uchun kirish');
    $('notificationVerify').textContent=t('Подтвердить email','Emailni tasdiqlash');$('notificationSave').textContent=t('Сохранить','Saqlash');
    try{render(await api());}catch(error){$('notificationError').textContent=error.message;$('notificationError').hidden=false;}
  });
})();
