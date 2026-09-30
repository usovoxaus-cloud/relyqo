(() => {
  const links = [
    ['overview', '/admin#dashboard', 'Обзор'],
    ['organizations', '/admin#applications', 'Организации'],
    ['moderation', '/admin/control#cases', 'Оценки и жалобы'],
    ['analytics', '/admin/analytics', 'Аналитика с ИИ'],
    ['editor', '/admin/editor', 'Редактор с ИИ'],
    ['ads', '/admin#ads', 'Реклама'],
    ['settings', '/admin/settings', 'Настройки'],
  ];
  function activeSection() {
    if (location.pathname === '/admin/settings') return 'settings';
    if (location.pathname === '/admin/editor') return 'editor';
    if (location.pathname === '/admin/analytics') return 'analytics';
    if (location.pathname === '/admin/control') {
      if (location.hash === '#operations') return 'settings';
      if (['#insights', '#actions'].includes(location.hash)) return 'analytics';
      if (location.hash === '#applications') return 'organizations';
      return 'moderation';
    }
    return ({'#applications': 'organizations', '#ads': 'ads', '#audit': 'settings'})[location.hash] || 'overview';
  }
  function render() {
    document.querySelectorAll('[data-management-nav]').forEach(nav => {
      nav.setAttribute('aria-label', 'Центр управления');
      nav.classList.add('managementNav');
      nav.replaceChildren(...links.map(([key, href, label]) => {
        const a = document.createElement('a');
        a.href = href;
        a.textContent = window.relyqoT?.(label) || label;
        if (key === activeSection()) a.setAttribute('aria-current', 'page');
        return a;
      }));
    });
  }
  window.addEventListener('hashchange', render);
  window.relyqoLanguageReady?.then(render);
  render();
})();
