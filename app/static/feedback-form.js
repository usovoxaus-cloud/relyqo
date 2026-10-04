(() => {
  const target = document.getElementById('feedbackFields');
  if (!target) return;
  const selected = new Set();
  const t = (ru, uz) => document.documentElement.lang === 'uz' ? uz : ru;
  let requestId = 0;
  const heading = document.createElement('h3'); heading.textContent = 'Что повлияло на вашу оценку?';
  const hint = document.createElement('p'); hint.textContent = 'Необязательно. Выберите до 5 причин. Ответ и комментарий видны вам и администратору RELYQO.';
  const options = document.createElement('div'); options.className = 'feedbackOptions';
  const label = document.createElement('label'); label.textContent = 'Короткий комментарий';
  const comment = document.createElement('textarea'); comment.id = 'feedbackComment'; comment.maxLength = 600; comment.rows = 3;
  comment.placeholder = 'Расскажите, что понравилось или что можно улучшить. Не указывайте телефоны и другие личные данные.';
  const count = document.createElement('p'); count.className = 'feedbackCount'; count.setAttribute('aria-live', 'polite');
  const updateCount = () => { count.textContent = t('Выбрано причин: ', 'Tanlangan sabablar: ') + selected.size + ' / 5'; };
  label.append(comment); target.append(heading, hint, options, count, label); updateCount();
  window.relyqoFeedback = () => ({reasons: [...selected], comment: comment.value.trim() || null});
  window.relyqoSetFeedbackCategory = (category = 'OTHER') => {
    const request = ++requestId;
    target.dataset.category = category;
    selected.clear(); updateCount(); options.replaceChildren();
    const loading = document.createElement('p'); loading.textContent = t('Загружаем причины…', 'Sabablar yuklanmoqda…'); options.append(loading);
    return fetch('/v1/public/feedback-reasons?category=' + encodeURIComponent(category)).then(r => {if(!r.ok) throw Error(); return r.json();}).then(data => {
    if (request !== requestId) return;
    options.replaceChildren();
    for(const item of data.items) {
      const l=document.createElement('label'), input=document.createElement('input'); input.type='checkbox'; input.value=item.code;
      const span=document.createElement('span'); span.textContent=(document.documentElement.lang==='uz'?item.label_uz:item.label);
      input.addEventListener('change',()=>{
        if(input.checked&&selected.size>=5){input.checked=false;count.textContent=t('Можно выбрать до 5 причин. Снимите одну, чтобы выбрать другую.', '5 tagacha sabab tanlash mumkin. Boshqasini tanlash uchun bittasini olib tashlang.');return;}
        if(input.checked)selected.add(item.code);else selected.delete(item.code);
        updateCount();
      });
      l.append(input,span); options.append(l);
    }
    }).catch(()=>{
      if (request !== requestId) return;
      options.replaceChildren();
      const note=document.createElement('p');note.textContent='Причины не загрузились. Можно оставить комментарий.';
      const retry=document.createElement('button');retry.type='button';retry.textContent=t('Повторить','Qayta urinish');
      retry.addEventListener('click',()=>window.relyqoSetFeedbackCategory(target.dataset.category));options.append(note,retry);
    });
  };
  window.relyqoSetFeedbackCategory(target.dataset.category || 'OTHER');
})();

