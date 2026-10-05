(() => {
  'use strict';
  const $=id=>document.getElementById(id),t=value=>window.relyqoT?.(value)||value;
  const admin=location.pathname==='/admin/representatives';
  const key=new URLSearchParams(location.search).get('object_key');
  const labels={PENDING:'На проверке',APPROVED:'Доступ подтверждён',REJECTED:'Отклонена',REVOKED:'Доступ отозван'};
  let busy=false,offset=0,version=null;
  function node(tag,text,authored=false){const n=document.createElement(tag);n.textContent=authored?text:t(text);if(authored)n.setAttribute('data-user-content','');return n;}
  async function api(url,body){
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),20000);let response,data;
    try{response=await fetch(url,{cache:'no-store',credentials:'same-origin',signal:controller.signal,...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});data=await response.json();}
    catch{throw Error(t('Не удалось связаться с сервером. Текст сохранён в форме. Проверьте соединение и повторите.'));}
    finally{clearTimeout(timeout);}
    if(!response.ok){if(response.status===401)$('claimsLogin').hidden=false;throw Error(typeof data.detail==='string'?t(data.detail):t('Проверьте данные заявки'));}return data;
  }
  async function run(task){if(busy)return;busy=true;$('claimsError').hidden=true;document.querySelectorAll('.requestsShell button,.requestsShell input,.requestsShell textarea,.requestsShell select').forEach(b=>b.disabled=true);try{await task();}catch(e){$('claimsError').textContent=e.message;$('claimsError').hidden=false;}finally{busy=false;document.querySelectorAll('.requestsShell button,.requestsShell input,.requestsShell textarea,.requestsShell select').forEach(b=>b.disabled=false);}}
  async function loadContext(){
    if(!key||admin)return;
    const data=await api('/v1/representation/context?object_key='+encodeURIComponent(key));
    $('claimName').textContent=data.organization.name;$('claimAddress').textContent=data.organization.address;
    const claim=data.claim;version=claim?.version||null;
    const editable=!claim||['REJECTED','REVOKED'].includes(claim.status);$('claimNew').hidden=!editable;
    if(claim&&editable){$('claimContact').value=claim.contact;$('claimEvidence').value=claim.evidence;}
    if(claim&&!editable){$('claimsNotice').textContent=t(labels[claim.status]);$('claimsNotice').hidden=false;}
  }
  function render(row){
    const card=node('article','');card.className='claimCard';card.append(node('h3',row.organization.name,true),node('p',row.organization.address,true));
    const status=node('p',labels[row.status]);status.className='badge';card.append(status);
    if(admin){card.append(node('p',t('Заявитель:')+' '+row.applicant,true));if(!row.applicant_active)card.append(node('p','Аккаунт отключён'));}
    card.append(node('h4','Рабочий контакт'),node('p',row.contact,true),node('h4','Основание полномочий'),node('p',row.evidence,true));
    if(row.decision_note)card.append(node('h4','Решение администратора'),node('p',row.decision_note,true));
    if(!admin){
      const a=node('a',row.status==='APPROVED'?'Открыть обращения':'Открыть заявку');a.className='button secondary';a.href=row.status==='APPROVED'?'/business/requests':'/representative?object_key='+encodeURIComponent(row.object_key);card.append(a);
    }else if(['PENDING','APPROVED'].includes(row.status)){
      const form=node('form',''),label=node('label','Основание решения'),note=document.createElement('textarea');note.required=true;note.minLength=20;note.maxLength=2000;note.rows=3;note.setAttribute('data-user-content','');label.append(note);form.append(label);
      const checkLabel=node('label',''),check=document.createElement('input');check.type='checkbox';checkLabel.className='check';checkLabel.append(check,node('span','Полномочия проверены по независимому официальному источнику; организация и адрес совпадают.'));
      if(row.status==='PENDING')form.append(checkLabel);
      const actions=row.status==='PENDING'?[['approve','Подтвердить доступ'],['reject','Отклонить заявку']]:[['revoke','Отозвать доступ']];
      for(const [action,title]of actions){const b=node('button',title);b.type='submit';b.value=action;b.className=action==='approve'?'':'secondary';form.append(b);}
      form.addEventListener('submit',event=>{event.preventDefault();const action=event.submitter?.value;if(!action)return;run(async()=>{
        if(action==='approve'&&!check.checked)throw Error(t('Подтвердите проверку полномочий активного заявителя'));
        await api('/v1/representation/claims/'+encodeURIComponent(row.id)+'/decision',{version:row.version,action,note:note.value,verified:check.checked});
        await loadList();window.dispatchEvent(new window.Event('relyqo-inbox-updated'));
      });});card.append(form);
    }
    $('claimsList').append(card);
  }
  async function loadList(reset=true){
    const next=reset?0:offset;const data=await api('/v1/representation/claims?offset='+next+'&status='+encodeURIComponent($('claimsFilter').value||'ALL'));
    if(data.admin!==admin)throw Error(t('Войдите в аккаунт для этого раздела'));
    if(reset)$('claimsList').replaceChildren();data.items.forEach(render);offset=next+data.items.length;
    if(!admin&&data.items.length){await api('/v1/representation/read',{items:data.items.map(row=>({id:row.id,version:row.version}))});window.dispatchEvent(new window.Event('relyqo-inbox-updated'));}
    $('claimsMore').hidden=!data.has_more;$('claimsPanel').hidden=false;$('claimsEmpty').hidden=offset>0;
  }
  $('claimForm').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
    if(!$('claimConsent').checked)throw Error(t('Подтвердите согласие на проверку полномочий'));
    await api('/v1/representation/claims',{object_key:key,contact:$('claimContact').value,evidence:$('claimEvidence').value,consent:$('claimConsent').checked,version});
    $('claimNew').hidden=true;$('claimConsent').checked=false;$('claimContact').value='';$('claimEvidence').value='';
    $('claimsNotice').textContent=t('Заявка отправлена. Решение появится в этом разделе.');$('claimsNotice').hidden=false;await loadList();
  });});
  $('claimsReload').addEventListener('click',()=>run(async()=>{await loadList();await loadContext();}));
  $('claimsMore').addEventListener('click',()=>run(()=>loadList(false)));
  $('claimsFilter').addEventListener('change',()=>run(()=>loadList()));
  $('claimsLoginLink').href=admin?'/admin':'/me?return_to='+encodeURIComponent(location.pathname+location.search);
  if(admin){$('claimsTitle').textContent=t('Проверка представителей');$('claimsListTitle').textContent=t('Заявки представителей');$('claimsLead').textContent=t('Проверьте полномочия по официальным контактам организации. Текст заявки сам по себе не подтверждает доступ.');$('claimsBack').href='/admin/requests';$('claimsBack').textContent=t('← В кабинет');$('claimsFilter').value='PENDING';$('claimsEmpty').textContent=t('Заявок с этим статусом нет.');}
  window.addEventListener('beforeunload',event=>{if(!$('claimNew').hidden&&($('claimContact').value||$('claimEvidence').value)){event.preventDefault();event.returnValue='';}});
  Promise.resolve(window.relyqoLanguageReady).then(()=>run(async()=>{await loadList();await loadContext();}));
})();
