(async () => {
  const status = document.getElementById('settingsStatus');
  try {
    const response = await fetch('/v1/auth/me', {cache:'no-store'});
    const user = await response.json();
    if (!response.ok || user.role !== 'RELYQO_ADMIN') throw Error('Доступ только администратору.');
    document.getElementById('settingsContent').hidden = false;
    status.textContent = '';
  } catch (error) {
    status.textContent = error.message || 'Не удалось проверить доступ.';
    document.getElementById('settingsLocked').hidden = false;
  }
})();
