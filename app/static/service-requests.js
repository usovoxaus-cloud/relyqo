/* Shared UI for consumer, verified owner and administrator; authorization is server-side. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const t = text => window.relyqoT?.(text) || text;
  const params = new URLSearchParams(location.search);
  const mode = location.pathname.startsWith('/admin/') ? 'admin' : location.pathname.startsWith('/business/') ? 'business' : 'consumer';
  const statuses = {WAITING_ORGANIZATION:'Ожидает подключения организации',OPEN:'Передано организации',IN_PROGRESS:'В работе',ANSWERED:'Организация ответила',RESOLVED:'Решено потребителем',WITHDRAWN:'Обращение отозвано'};
  let selected = null, offset = 0, busy = false, detailGeneration = 0;
  const drafts = {request: {kind:'new', context:null, version:0, message:'', known:false, generation:0}, reply: {kind:'reply', context:null, version:0, message:'', known:false, generation:0}};
  function dirtyDraft(name) {
    const state = drafts[name], value = $(name+'Text').value.trim();
    return Boolean(value && (!state.known || value !== state.message));
  }
  function draftControls(name) {
    const state = drafts[name];
    $(name+'DraftSave').disabled = busy || !state.context || !state.known || !$(name+'Text').value.trim();
    $(name+'DraftRestore').disabled = busy || !state.context;
    $(name+'DraftDelete').disabled = busy || !state.context || !state.version;
  }
  function draftUrl(state) {
    return '/v1/request-drafts/'+state.kind+'/'+encodeURIComponent(state.context);
  }
  async function loadDraft(name, context, replace = false) {
    const state = drafts[name], generation = ++state.generation, before = $(name+'Text').value;
    state.context = context;
    if (!context) { state.known=false; state.version=0; state.message=''; draftControls(name); return; }
    try {
      const result = await api(draftUrl(state));
      if (generation !== state.generation || context !== state.context) return;
      state.version=result.draft?.version || 0; state.message=result.draft?.message || ''; state.known=true;
      if (result.draft && $(name+'Text').value === before && (!before || replace)) $(name+'Text').value=state.message;
      text(name+'DraftStatus', result.draft ? (dirtyDraft(name) ? 'Есть несохранённые изменения.' : 'Черновик восстановлен.') : 'Сохранённого черновика нет.');
    } catch (error) {
      if (generation !== state.generation || context !== state.context) return;
      state.known=false;
      text(name+'DraftStatus','Не удалось загрузить черновик. Текст в форме сохранён. Нажмите «Восстановить черновик» для повтора.');
      if (error.message) showError(error);
    } finally { draftControls(name); }
  }
  for (const name of ['request','reply']) {
    $(name+'Text').addEventListener('input',()=>{
      text(name+'DraftStatus',dirtyDraft(name)?'Есть несохранённые изменения.':drafts[name].version?'Черновик сохранён.':'Сохранённого черновика нет.'); draftControls(name);
    });
    $(name+'DraftSave').addEventListener('click',()=>run(async()=>{
      const state=drafts[name];
      if (!state.known || !state.context) return;
      const result=await api(draftUrl(state),{message:$(name+'Text').value,version:state.version});
      state.version=result.draft.version;state.message=result.draft.message;
      text(name+'DraftStatus','Черновик сохранён.');
    }));
    $(name+'DraftRestore').addEventListener('click',()=>run(async()=>{
      if (dirtyDraft(name) && !window.confirm(t('Заменить неотправленный текст сохранённым черновиком?'))) return;
      await loadDraft(name,drafts[name].context,true);
    }));
    $(name+'DraftDelete').addEventListener('click',()=>run(async()=>{
      const state=drafts[name];
      if (!state.version || !window.confirm(t('Удалить сохранённый черновик? Текст в форме останется.'))) return;
      await api(draftUrl(state)+'/remove',{version:state.version});
      state.version=0;state.message='';text(name+'DraftStatus','Сохранённый черновик удалён.');
    }));
    draftControls(name);
  }
  function text(id, value) { $(id).textContent = t(value); }
  function showError(error) { text('requestError', error.message); $('requestError').hidden = false; }
  function clearError() { $('requestError').hidden = true; }
  function date(value) { return new Date(value).toLocaleString(document.documentElement.lang === 'uz' ? 'uz-UZ' : 'ru-RU', {dateStyle:'short',timeStyle:'short'}); }
  async function api(url, body) {
    if(url.startsWith('/v1/service-requests') || url.startsWith('/v1/request-drafts'))url+=(url.includes('?')?'&':'?')+'view='+mode;
    let response, data;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      response = await fetch(url, {credentials:'same-origin',cache:'no-store',signal:controller.signal,...(body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {})});
      data = await response.json();
    } catch {
      throw new Error(t('Не удалось связаться с сервером. Текст сохранён в форме. Проверьте соединение и повторите.'));
    } finally {
      clearTimeout(timeout);
    }
    if (!response.ok) {
      if (response.status === 401) $('loginGate').hidden = false;
      throw new Error(typeof data.detail === 'string' ? data.detail : t('Не удалось выполнить действие. Проверьте данные и повторите.'));
    }
    return data;
  }
  async function run(task) {
    if (busy) return;
    busy = true; clearError();
    const controls = '.requestsShell button,.requestsShell input,.requestsShell textarea,.requestsShell select';
    document.querySelectorAll(controls).forEach(control => { control.disabled = true; });
    try { await task(); } catch (error) { showError(error); }
    finally { busy = false; document.querySelectorAll(controls).forEach(control => { control.disabled = false; }); for (const name of ['request','reply']) draftControls(name); }
  }
  function element(tag, value, authored = false) {
    const node = document.createElement(tag); node.textContent = authored ? value : t(value);
    if (authored) node.setAttribute('data-user-content','');
    return node;
  }
  async function loadList(reset = true) {
    const nextOffset = reset ? 0 : offset;
    const data = await api('/v1/service-requests?offset=' + nextOffset + '&filter=' + encodeURIComponent($('requestFilter').value || 'ALL'));
    const allowed = mode === 'consumer' ? data.role === 'CONSUMER' : mode === 'admin' ? data.role === 'RELYQO_ADMIN' : ['BUSINESS_OWNER','FREGAT_OWNER','REPRESENTATIVE'].includes(data.role);
    if (!allowed) throw new Error(t('Войдите в аккаунт для этого раздела'));
    if (reset) $('requestList').replaceChildren();
    for (const item of data.items) {
      const button = element('button',''); button.type = 'button'; button.className = 'requestCard'; button.dataset.id = item.id;
      button.setAttribute('aria-current',String(item.id === selected?.id));
      button.append(element('strong',item.organization.name,true),element('span',statuses[item.status]),element('small',date(item.updated_at),true));
      if(item.unread){const badge=element('span','Непрочитанное');badge.className='badge';button.append(badge);}
      if(item.overdue)button.append(element('small','Без ответа более 48 часов'));
      if(item.waiting_hours!==null&&item.waiting_hours!==undefined)button.append(element('small',t('Часы ожидания:')+' '+item.waiting_hours,true));
      button.addEventListener('click',() => run(() => openConversation(item.id)));
      $('requestList').append(button);
    }
    offset = nextOffset + data.items.length;
    $('emptyRequests').hidden = offset > 0; $('moreRequests').hidden = !data.has_more; $('inbox').hidden = false;
    if($('requestFilter').value!=='ALL')text('emptyRequests','Нет обращений с этим статусом. Выберите другой фильтр.');
    else text('emptyRequests',mode==='consumer'?'Обращений пока нет. Откройте свою оценку в профиле и нажмите «Получить ответ организации».':'Обращений пока нет. Здесь появятся сообщения, которые потребители согласились передать организации.');
    if(mode!=='consumer'&&data.summary){
      const s=data.summary;$('requestStats').hidden=false;$('statsGrid').replaceChildren();
      for(const [label,value] of [['Всего обращений',s.total],['Нужен ответ организации',s.needs_reply],['Решено потребителем',s.resolved],['Доля решённых',s.resolution_percent===null?'—':s.resolution_percent+'%'],['Первый ответ',s.first_response_hours===null?'—':s.first_response_hours+' '+t('ч.')],['Ожидают подключения',s.waiting_organization]]){
        const cell=element('div','');cell.append(element('strong',String(value),true),element('span',label));$('statsGrid').append(cell);
      }
      text('statsSample',t('На основе ответов:')+' '+s.response_sample+'. '+t('Без ответа более 48 часов:')+' '+s.overdue);
    }
  }
  function actionButton(label, action, className = 'secondary') {
    const button = element('button',label); button.type = 'button'; button.className = className;
    button.addEventListener('click',() => run(async () => {
      if (action === 'withdraw' && !window.confirm(t('Отозвать обращение? Доступ организации к переписке будет закрыт. Уже прочитанные сообщения нельзя отменить.'))) return;
      await sendAction(action);
    }));
    $('requestActions').append(button);
  }
  function renderConversation(item) {
    selected = item; $('conversation').hidden = false; $('actionNotice').hidden = true;
    $('conversationName').textContent = item.organization.name; $('conversationAddress').textContent = item.organization.address;
    text('conversationStatus',statuses[item.status]);
    const hints = {
      WAITING_ORGANIZATION:'Кабинет организации ещё не подключён. Администратор проверит получателя. Срок ответа пока неизвестен.',
      OPEN:'Обращение доступно подтверждённой организации. Ответ появится здесь.',
      IN_PROGRESS:'Обсуждение продолжается. Новые сообщения появятся в этом разделе.',
      ANSWERED:'Прочитайте ответ. Если вопрос закрыт, потребитель может подтвердить решение.',
      RESOLVED:'Потребитель подтвердил решение. При необходимости он может продолжить обсуждение.',
      WITHDRAWN:'Доступ организации закрыт. Уже прочитанные сообщения отозвать невозможно.'
    };
    text('conversationHint',hints[item.status]);
    $('recipient').hidden = !item.recipient; $('recipientName').textContent = item.recipient || '';
    $('messages').replaceChildren();
    for (const message of item.messages) {
      const card = element('article',''); card.className = 'message ' + (message.side === 'CONSUMER' ? 'consumer' : 'business');
      card.append(element('b',message.side === 'CONSUMER' ? 'Потребитель' : 'Организация'),element('small',date(message.created_at),true),element('p',message.body,true));
      $('messages').append(card);
    }
    $('requestActions').replaceChildren();
    const closed = ['RESOLVED','WITHDRAWN'].includes(item.status);
    $('replyForm').hidden = mode === 'admin' || item.status === 'WITHDRAWN' || (mode === 'business' && closed);
    text('sendReply',item.status === 'RESOLVED' ? 'Продолжить обсуждение' : 'Отправить сообщение');
    if (mode === 'consumer') {
      if (item.status === 'ANSWERED') actionButton('Проблема решена','resolve','');
      if (item.status !== 'WITHDRAWN') actionButton('Отозвать обращение','withdraw','secondary danger');
    } else if (mode === 'business' && item.status === 'OPEN') actionButton('Взять в работу','start','');
    $('assignment').hidden = mode !== 'admin' || item.status !== 'WAITING_ORGANIZATION';
    $('assignForm').hidden = true; $('branchResult').textContent = ''; $('matchConfirmed').checked = false;
    document.querySelectorAll('.requestCard').forEach(button => button.setAttribute('aria-current',String(button.dataset.id === item.id)));
  }
  async function openConversation(id, focus = true) {
    const generation = ++detailGeneration;
    const item = await api('/v1/service-requests/' + encodeURIComponent(id));
    if (generation !== detailGeneration) return;
    const changed = selected?.id !== id;
    if (changed && dirtyDraft('reply') && !window.confirm(t('Открыть другое обращение и удалить неотправленный текст?'))) return;
    if (changed) $('replyText').value = '';
    renderConversation(item);
    if (!$('replyForm').hidden && (changed || !drafts.reply.known)) await loadDraft('reply',id);
    try{await api('/v1/service-requests/'+encodeURIComponent(id)+'/read',{version:item.version});window.dispatchEvent(new window.Event('relyqo-inbox-updated'));await loadList();}catch(error){showError(error);}
    if (focus) { $('conversation').focus({preventScroll:true}); $('conversation').scrollIntoView({behavior:'smooth',block:'start'}); }
  }
  async function sendAction(action, message = '') {
    const item = await api('/v1/service-requests/' + encodeURIComponent(selected.id) + '/actions', {version:selected.version,action,message});
    renderConversation(item);
    if (['reply','reopen'].includes(action)) {
      $('replyText').value = '';
      drafts.reply.version=0;drafts.reply.message='';
      if (!$('replyForm').hidden) await loadDraft('reply',item.id);
    }
    text('actionNotice','Сохранено'); $('actionNotice').hidden = false;
    await loadList();
    window.dispatchEvent(new window.Event('relyqo-inbox-updated'));
  }
  async function setupCreate() {
    const ratingId = params.get('rating_id'); if (!ratingId || mode !== 'consumer') return;
    const data = await api('/v1/service-requests/context?rating_id=' + encodeURIComponent(ratingId));
    if (data.existing_id) { await openConversation(data.existing_id); return; }
    $('newOrganization').textContent = data.organization.name; $('newAddress').textContent = data.organization.address;
    text('deliveryNote',data.ready ? 'Сообщение получит подтверждённая организация. Ответ появится в разделе «Ответы организаций».' : 'Кабинет организации ещё не подключён. Администратор проверит получателя. Срок ответа пока неизвестен.');
    $('newRequest').hidden = false;
    await loadDraft('request',ratingId);
  }
  $('createRequestForm').addEventListener('submit', event => { event.preventDefault(); run(async () => {
    if (!$('shareConsent').checked) throw new Error(t('Подтвердите согласие на передачу текста организации'));
    const item = await api('/v1/service-requests',{rating_id:params.get('rating_id'),message:$('requestText').value,consent:$('shareConsent').checked});
    $('newRequest').hidden = true; $('requestText').value = ''; $('shareConsent').checked = false;
    await loadDraft('request',null);
    renderConversation(item); await loadList(); $('conversation').scrollIntoView({behavior:'smooth',block:'start'});
    if (!$('replyForm').hidden) await loadDraft('reply',item.id);
  }); });
  $('replyForm').addEventListener('submit',event => { event.preventDefault(); run(() => sendAction(selected.status === 'RESOLVED' ? 'reopen' : 'reply',$('replyText').value)); });
  $('reloadList').addEventListener('click',() => run(() => loadList()));
  $('requestFilter').addEventListener('change',() => run(() => loadList()));
  $('moreRequests').addEventListener('click',() => run(() => loadList(false)));
  $('reloadConversation').addEventListener('click',() => run(() => openConversation(selected.id,false)));
  $('branchSearch').addEventListener('submit',event => { event.preventDefault(); run(async () => {
    const data = await api('/v1/service-requests/branches?q=' + encodeURIComponent($('branchQuery').value.trim()));
    $('branchChoice').replaceChildren();
    const placeholder = element('option','Выберите филиал'); placeholder.value = ''; $('branchChoice').append(placeholder);
    for (const branch of data.items) { const option = element('option',branch.name + ' · ' + branch.address,true); option.value = branch.id; $('branchChoice').append(option); }
    $('assignForm').hidden = !data.items.length; $('matchConfirmed').checked = false;
    text('branchResult',data.items.length ? 'Сверьте адрес перед передачей обращения.' : 'Подтверждённые организации с активным владельцем не найдены.');
  }); });
  $('assignForm').addEventListener('submit',event => { event.preventDefault(); run(async () => {
    const item = await api('/v1/service-requests/' + encodeURIComponent(selected.id) + '/assign',{version:selected.version,branch_id:$('branchChoice').value,confirmed:$('matchConfirmed').checked,note:$('assignmentNote').value});
    renderConversation(item); await loadList();
  }); });
  const back = mode === 'admin' ? '/admin/control' : mode === 'business' ? '/business-owner' : '/me';
  $('backLink').href = back;
  $('loginLink').href = (mode === 'consumer' ? '/me?return_to=' + encodeURIComponent(location.pathname + location.search) : mode === 'business' ? '/business-owner' : '/admin');
  if (mode !== 'consumer') {
    text('pageTitle',mode === 'admin' ? 'Обращения к организациям' : 'Обращения потребителей');
    text('inboxTitle','Обращения'); text('backLink','← В кабинет');
    text('pageLead',mode === 'admin' ? 'Подключайте проверенные организации к обращениям. Решение подтверждает потребитель.' : 'Ответьте потребителю и помогите решить вопрос. Завершение подтверждает сам потребитель.');
    text('emptyRequests','Обращений пока нет. Здесь появятся сообщения, которые потребители согласились передать организации.');
  }
  if(mode==='admin')$('claimsAdminLink').hidden=false;
  if(mode==='business'){$('backLink').href='/representative';$('loginLink').href='/me?return_to='+encodeURIComponent(location.pathname+location.search);$('ownerLoginLink').hidden=false;}
  if(['ALL','UNREAD','NEEDS_REPLY','OVERDUE','WAITING_ORGANIZATION','ANSWERED','RESOLVED','WITHDRAWN'].includes(params.get('filter')))$('requestFilter').value=params.get('filter');
  // Only an explicit save persists text behind account authorization; never browser storage.
  window.addEventListener('beforeunload',event => { if (dirtyDraft('reply') || dirtyDraft('request')) { event.preventDefault(); event.returnValue = ''; } });
  Promise.resolve(window.relyqoLanguageReady).then(() => run(async () => { await loadList(); await setupCreate(); if(params.get('id')) await openConversation(params.get('id')); }));
})();
