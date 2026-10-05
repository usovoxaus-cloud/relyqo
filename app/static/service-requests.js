/* Shared UI for consumer, verified owner and administrator; authorization is server-side. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const t = text => window.relyqoT?.(text) || text;
  const params = new URLSearchParams(location.search);
  const mode = location.pathname.startsWith('/admin/') ? 'admin' : location.pathname.startsWith('/business/') ? 'business' : 'consumer';
  const statuses = {WAITING_ORGANIZATION:'Ожидает подключения организации',OPEN:'Передано организации',IN_PROGRESS:'В работе',ANSWERED:'Организация ответила',RESOLVED:'Решено потребителем',WITHDRAWN:'Обращение отозвано'};
  let selected = null, offset = 0, busy = false, detailGeneration = 0;
  function text(id, value) { $(id).textContent = t(value); }
  function showError(error) { text('requestError', error.message); $('requestError').hidden = false; }
  function clearError() { $('requestError').hidden = true; }
  function date(value) { return new Date(value).toLocaleString(document.documentElement.lang === 'uz' ? 'uz-UZ' : 'ru-RU', {dateStyle:'short',timeStyle:'short'}); }
  async function api(url, body) {
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
    finally { busy = false; document.querySelectorAll(controls).forEach(control => { control.disabled = false; }); }
  }
  function element(tag, value, authored = false) {
    const node = document.createElement(tag); node.textContent = authored ? value : t(value);
    if (authored) node.setAttribute('data-user-content','');
    return node;
  }
  async function loadList(reset = true) {
    const nextOffset = reset ? 0 : offset;
    const data = await api('/v1/service-requests?offset=' + nextOffset);
    const allowed = mode === 'consumer' ? data.role === 'CONSUMER' : mode === 'admin' ? data.role === 'RELYQO_ADMIN' : ['BUSINESS_OWNER','FREGAT_OWNER'].includes(data.role);
    if (!allowed) throw new Error(t('Войдите в аккаунт для этого раздела'));
    if (reset) $('requestList').replaceChildren();
    for (const item of data.items) {
      const button = element('button',''); button.type = 'button'; button.className = 'requestCard'; button.dataset.id = item.id;
      button.setAttribute('aria-current',String(item.id === selected?.id));
      button.append(element('strong',item.organization.name,true),element('span',statuses[item.status]),element('small',date(item.updated_at),true));
      button.addEventListener('click',() => run(() => openConversation(item.id)));
      $('requestList').append(button);
    }
    offset = nextOffset + data.items.length;
    $('emptyRequests').hidden = offset > 0; $('moreRequests').hidden = !data.has_more; $('inbox').hidden = false;
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
    if (selected?.id !== id && $('replyText').value && !window.confirm(t('Открыть другое обращение и удалить неотправленный текст?'))) return;
    if (selected?.id !== id) $('replyText').value = '';
    renderConversation(item);
    if (focus) { $('conversation').focus({preventScroll:true}); $('conversation').scrollIntoView({behavior:'smooth',block:'start'}); }
  }
  async function sendAction(action, message = '') {
    const item = await api('/v1/service-requests/' + encodeURIComponent(selected.id) + '/actions', {version:selected.version,action,message});
    renderConversation(item); $('replyText').value = '';
    text('actionNotice','Сохранено'); $('actionNotice').hidden = false;
    await loadList();
  }
  async function setupCreate() {
    const ratingId = params.get('rating_id'); if (!ratingId || mode !== 'consumer') return;
    const data = await api('/v1/service-requests/context?rating_id=' + encodeURIComponent(ratingId));
    if (data.existing_id) { await openConversation(data.existing_id); return; }
    $('newOrganization').textContent = data.organization.name; $('newAddress').textContent = data.organization.address;
    text('deliveryNote',data.ready ? 'Сообщение получит подтверждённая организация. Ответ появится в разделе «Ответы организаций».' : 'Кабинет организации ещё не подключён. Администратор проверит получателя. Срок ответа пока неизвестен.');
    $('newRequest').hidden = false;
  }
  $('createRequestForm').addEventListener('submit', event => { event.preventDefault(); run(async () => {
    if (!$('shareConsent').checked) throw new Error(t('Подтвердите согласие на передачу текста организации'));
    const item = await api('/v1/service-requests',{rating_id:params.get('rating_id'),message:$('requestText').value,consent:$('shareConsent').checked});
    $('newRequest').hidden = true; $('requestText').value = ''; $('shareConsent').checked = false;
    renderConversation(item); await loadList(); $('conversation').scrollIntoView({behavior:'smooth',block:'start'});
  }); });
  $('replyForm').addEventListener('submit',event => { event.preventDefault(); run(() => sendAction(selected.status === 'RESOLVED' ? 'reopen' : 'reply',$('replyText').value)); });
  $('reloadList').addEventListener('click',() => run(() => loadList()));
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
  // Drafts stay only in memory and are never stored in browser storage.
  window.addEventListener('beforeunload',event => { if ($('replyText').value || $('requestText').value) { event.preventDefault(); event.returnValue = ''; } });
  Promise.resolve(window.relyqoLanguageReady).then(() => run(async () => { await loadList(); await setupCreate(); if(params.get('id')) await openConversation(params.get('id')); }));
})();
