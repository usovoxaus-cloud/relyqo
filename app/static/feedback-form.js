(() => {
  const target = document.getElementById('feedbackFields');
  if (!target) return;
  const selected = new Set();
  const heading = document.createElement('h3'); heading.textContent = 'Что повлияло на вашу оценку?';
  const hint = document.createElement('p'); hint.textContent = 'Необязательно. Выберите до 5 причин. Ответ и комментарий видны вам и администратору RELYQO.';
  const options = document.createElement('div'); options.className = 'feedbackOptions';
  const label = document.createElement('label'); label.textContent = 'Короткий комментарий';
  const comment = document.createElement('textarea'); comment.id = 'feedbackComment'; comment.maxLength = 600; comment.rows = 3;
  comment.placeholder = 'Расскажите, что понравилось или что можно улучшить. Не указывайте телефоны и другие личные данные.';
  label.append(comment); target.append(heading, hint, options, label);
  window.relyqoFeedback = () => ({reasons: [...selected], comment: comment.value.trim() || null});
  fetch('/v1/public/feedback-reasons').then(r => {if(!r.ok) throw Error(); return r.json();}).then(data => {
    for(const item of data.items) {
      const l=document.createElement('label'), input=document.createElement('input'); input.type='checkbox'; input.value=item.code;
      const span=document.createElement('span'); span.textContent=(document.documentElement.lang==='uz'?item.label_uz:item.label);
      input.addEventListener('change',()=>{if(input.checked&&selected.size>=5){input.checked=false;return;}if(input.checked)selected.add(item.code);else selected.delete(item.code);});
      l.append(input,span); options.append(l);
    }
  }).catch(()=>{const note=document.createElement('p');note.textContent='Причины не загрузились. Можно оставить комментарий.';options.append(note);});
})();
