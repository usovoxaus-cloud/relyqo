/* Private in-app inbox; no browser permissions or external messages. */
(() => {
  'use strict';
  if (document.getElementById('engagementInbox')) return;
  const t = value => window.relyqoT?.(value) || value;
  const box = document.createElement('aside'); box.id = 'engagementInbox'; box.hidden = true;
  box.setAttribute('aria-label',t('Уведомления об обращениях'));
  const head = document.createElement('button'); head.type='button'; head.className='engagementToggle'; head.setAttribute('aria-expanded','false');
  const content=document.createElement('div');content.hidden=true;content.id='engagementContent';head.setAttribute('aria-controls',content.id);
  const status=document.createElement('p');status.className='engagementStatus';status.setAttribute('role','status');
  const links=document.createElement('div');links.className='engagementLinks';
  content.append(status,links);box.append(head,content);
  const mount=document.querySelector('main:not(#loginView):not(#authView)');(mount||document.body).prepend(box);
  head.addEventListener('click',()=>{content.hidden=!content.hidden;head.setAttribute('aria-expanded',String(!content.hidden));});
  function link(label,href,authored=false){const a=document.createElement('a');a.textContent=authored?label:t(label);a.href=href;if(authored)a.setAttribute('data-user-content','');links.append(a);return a;}
  let busy=false,stopped=false,timer;
  async function refresh(){
    if(busy||stopped||document.hidden)return;
    busy=true;const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);
    try{
      const response=await fetch('/v1/engagement/inbox',{credentials:'same-origin',cache:'no-store',signal:controller.signal});
      if([401,403].includes(response.status)){box.hidden=true;links.replaceChildren();return;}
      if(!response.ok)throw Error('inbox unavailable');
      const data=await response.json();box.hidden=false;
      const count=data.unread+data.pending_claims;
      head.textContent=t('Уведомления')+(count?' · '+count:'');
      status.textContent=data.unread?t('Непрочитанных обращений:')+' '+data.unread:t('Новых сообщений нет');
      links.replaceChildren();
      for(const item of data.items){
        const a=link(item.name,item.href,true);const label=document.createElement('span');label.removeAttribute('data-user-content');
        label.textContent=t(item.status.startsWith('CLAIM_')?'Есть решение по вашей заявке':item.status==='ANSWERED'?'Организация ответила':'Обращение обновлено');a.append(document.createTextNode(' · '),label);
      }
      if(data.overdue)link(t('Без ответа более 48 часов:')+' '+data.overdue,(data.admin?'/admin':'/business')+'/requests?filter=OVERDUE',true);
      if(data.pending_claims)link(t('Заявки представителей:')+' '+data.pending_claims,'/admin/representatives',true);
      if(data.business)link('Кабинет представителя','/business/requests');
      link('Открыть обращения',data.admin?'/admin/requests':data.business?'/business/requests':'/me/requests');
      if(!data.admin)link('Мои заявки представителя','/representative');
    }catch{if(!box.hidden)status.textContent=t('Не удалось обновить уведомления. Повторим при подключении.');}
    finally{busy=false;clearTimeout(timeout);}
  }
  document.addEventListener('visibilitychange',refresh);
  window.addEventListener('relyqo-inbox-updated',refresh);
  window.addEventListener('online',refresh);
  window.addEventListener('pagehide',()=>clearInterval(timer));
  Promise.resolve(window.relyqoLanguageReady).then(()=>{refresh();timer=setInterval(refresh,45000);});
})();
