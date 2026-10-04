(() => {
  const $ = id => document.getElementById(id);
  const objectKey = new URLSearchParams(location.search).get('object_key') || '';
  const date = value => value ? new Date(value).toLocaleDateString(document.documentElement.lang || 'ru') : 'нет оценок';
  function favorites() {
    try { const items = JSON.parse(localStorage.getItem('relyqo_favorites_v1') || '[]'); return new Set(Array.isArray(items) ? items : []); }
    catch { return new Set(); }
  }
  function refreshFavorite() {
    const saved = favorites().has(objectKey);
    $('favorite').textContent = saved ? '♥ В избранном' : '♡ В избранное';
    $('favorite').classList.toggle('saved', saved);
  }
  function caption(count, latest, minimum) {
    return `${count} оценок · ${count < minimum ? 'предварительный результат, меньше ' + minimum + ' оценок' : 'достаточно оценок для участия в рейтинге'} · последняя: ${date(latest)}`;
  }
  async function load() {
    $('rate').classList.add('hidden'); $('favorite').disabled = true;
    try {
      const response = await fetch(`/v1/public/place?object_key=${encodeURIComponent(objectKey)}`, {cache: 'no-store'});
      if (!response.ok) throw Error(response.status === 404 ? 'Организация не найдена. Вернитесь в поиск.' : 'Не удалось загрузить карточку. Обновите страницу.');
      const data = await response.json();
      window.relyqoGoogleRating?.mount($('googleRating'), data.google_reference || {});
      // URL text, scores and status are never trusted. The object key only identifies the record.
      $('name').textContent = data.name;
      const category = document.createElement('span'), address = document.createElement('span');
      category.textContent = data.category_label || ''; address.textContent = data.address || ''; address.dataset.userContent = 'true';
      $('address').replaceChildren(category, document.createTextNode(data.category_label && data.address ? ' · ' : ''), address);
      $('description').textContent = data.description || '';
      document.querySelector('title').setAttribute('data-user-content', 'true');
      document.title = `${data.name} — RELYQO`;
      const partner = data.profile_status === 'VERIFIED_PARTNER';
      $('source').textContent = partner ? 'ПАРТНЁР RELYQO' : data.source_url ? 'АДРЕС ПО САЙТУ ЗАВЕДЕНИЯ' : data.source === 'MANUAL' ? 'ДОБАВЛЕНО ПОТРЕБИТЕЛЕМ' : 'ПРОФИЛЬ RELYQO';
      $('hero').classList.toggle('partner', partner);
      if (data.source_url?.startsWith('https://')) {
        const reference = document.createElement('a'); reference.href = data.source_url; reference.target = '_blank'; reference.rel = 'noopener'; reference.className = 'sourceReference'; reference.textContent = `Источник адреса · проверен ${date(data.source_checked_at)}`; $('address').after(reference);
      }
      $('verifiedScore').textContent = data.verified_rating_count ? `${Number(data.relyqo_score).toFixed(1)}/100` : '—';
      $('verifiedCaption').textContent = `${caption(data.verified_rating_count, data.verified_last_rating_at, data.minimum_ratings)}. ${data.verified_visit_count} принятых QR-посещений. Оценки всей организации.`;
      $('communityScore').textContent = data.community_rating_count ? `${Number(data.community_score).toFixed(1)}/100` : '—';
      $('communityCaption').textContent = caption(data.community_rating_count, data.community_last_rating_at, data.minimum_ratings) + '. Без подтверждения QR; отдельный показатель.';
      const metrics = data.verified_rating_count ? data.verified_metrics : data.community_metrics;
      $('metricGrid').replaceChildren();
      if (data.verified_rating_count || data.community_rating_count) {
        for (const key of ['quality', 'service', 'cleanliness', 'value']) {
          const cell = document.createElement('div'), label = document.createElement('span'), score = document.createElement('b');
          cell.className = 'metricCell'; label.textContent = data.metric_labels[key];
          score.textContent = `${Number(metrics[key]).toFixed(1)}/100`; cell.append(label, score); $('metricGrid').append(cell);
        }
        $('breakdownLead').textContent = data.verified_rating_count ? 'Оценки по одноразовым QR организации.' : 'Community: оценки без QR.';
      } else $('breakdownLead').textContent = 'Показатели появятся после первых оценок.';
      $('rate').href = `/community-rate?${new URLSearchParams({object_key: objectKey, source: data.source, name: data.name, address: data.address || '', category: data.category})}`;
      $('rate').textContent = 'Оценить без QR'; $('rate').classList.remove('hidden');
      if (partner) {
        const qr = document.createElement('a'); qr.href = '/rate'; qr.className = 'button primary'; qr.textContent = 'Оценить по QR'; $('rate').before(qr);
      }
      refreshFavorite(); $('favorite').disabled = false;
      $('favorite').addEventListener('click', async () => {
        const items = favorites(), saved = !items.has(objectKey);
        if (saved) items.add(objectKey); else items.delete(objectKey);
        try { localStorage.setItem('relyqo_favorites_v1', JSON.stringify([...items])); refreshFavorite(); }
        catch { $('error').textContent = 'Браузер не разрешает сохранить избранное.'; $('error').classList.remove('hidden'); return; }
        try { await fetch('/v1/consumer/favorites', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({object_key:objectKey,source:data.source,saved}),cache:'no-store'}); } catch {}
      });
    } catch (error) { $('error').textContent = error.message; $('error').classList.remove('hidden'); }
  }
  load();
})();

