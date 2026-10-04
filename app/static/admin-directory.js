(() => {
  const $ = id => document.getElementById(id);
  let next = null, requestId = 0, currentQuery = '';
  const statuses = {SELF_REGISTERED:'На проверке', PUBLISHED:'Опубликована', VERIFIED_PARTNER:'QR подключён', REJECTED:'Отклонена'};
  const el = (tag, text) => { const n = document.createElement(tag); n.textContent = text; return n; };
  async function load(append = false) {
    const queryText = $('directoryQuery').value.trim();
    if (append && queryText !== currentQuery) append = false;
    const id = ++requestId;
    $('directoryMore').disabled = true;
    $('directoryStatus').textContent = 'Загружаем организации…';
    try {
      const query = new URLSearchParams({q:queryText, offset:String(append ? next || 0 : 0)});
      const response = await fetch('/v1/admin/organizations?' + query, {cache:'no-store'});
      const data = await response.json();
      if (id !== requestId) return;
      if (!response.ok) throw Error(data.detail || 'Не удалось загрузить организации');
      if (!append) $('organizationDirectory').replaceChildren();
      data.items.forEach(org => {
        const card = el('article', ''); card.className = 'appCard';
        const title = el('h3', org.name); title.dataset.userContent = 'true';
        card.append(title, el('p', `${org.city || ''} · ${window.relyqoCategoryLabel?.(org.category) || org.category} · ${statuses[org.profile_status] || org.profile_status}`));
        card.append(el('p', org.rating_count ? `Подтверждённые оценки: ${org.rating_count} · ${Number(org.score).toFixed(1)}/100` : 'Подтверждённых оценок пока нет'));
        const details = el('details', ''); details.append(el('summary', `Филиалы: ${org.branches.length}`));
        org.branches.forEach(branch => {
          const p = el('p', ''), details = el('span', `${branch.name} · ${branch.address || branch.city || ''}`);
          details.dataset.userContent = 'true'; p.append(details);
          if (!branch.active) p.append(el('span', ' · неактивен'));
          if (branch.active && ['PUBLISHED','VERIFIED_PARTNER'].includes(org.profile_status)) {
            const a = el('a', ' Открыть карточку →');
            a.href = '/place?' + new URLSearchParams({object_key:'relyqo:' + branch.id,source:'RELYQO_PARTNER',name:org.name,category_code:org.category,category:window.relyqoCategoryLabel?.(org.category)||org.category,address:branch.address||branch.city||'',profile_status:org.profile_status,verified_score:org.score,verified_count:org.rating_count}); p.append(a);
          }
          details.append(p);
        });
        card.append(details); $('organizationDirectory').append(card);
      });
      currentQuery = queryText; next = data.next_offset; $('directoryMore').hidden = next == null;
      $('directoryStatus').textContent = data.total ? `Найдено организаций: ${data.total}` : 'Организации не найдены.';
    } catch(error) {
      if (id === requestId) $('directoryStatus').textContent = error.message;
    } finally { if (id === requestId) $('directoryMore').disabled = false; }
  }
  $('directoryForm').addEventListener('submit', event => {event.preventDefault(); load();});
  $('directoryMore').addEventListener('click', () => load(true));
  document.addEventListener('relyqo:admin-loaded', () => load());
  if (!$('appView').classList.contains('hidden')) load();
})();

