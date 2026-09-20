(() => {
  'use strict';
  const form = document.getElementById('backupForm');
  const status = document.getElementById('backupStatus');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter || form.querySelector('button[type="submit"]');
    if (button.disabled) return;
    button.disabled = true;
    let writable;
    try {
      const body = Object.fromEntries(new FormData(form));
      if (body.passphrase !== body.confirm_passphrase) throw Error('Пароли копии не совпадают.');
      const filename = 'relyqo-' + new Date().toISOString().replace(/[:.]/g, '-') + '.rqbackup';
      let handle;
      if (typeof window.showSaveFilePicker === 'function') {
        status.textContent = 'Выберите папку для сохранения копии, например D:\\Relico.';
        // Request the native dialog during the user's click, before any network work.
        handle = await window.showSaveFilePicker({
          id: 'relyqo-backup', suggestedName: filename,
          types: [{description: 'RELYQO backup', accept: {'application/octet-stream': ['.rqbackup']}}]
        });
      }
      status.textContent = 'Создаём зашифрованную копию…';
      const response = await fetch('/v1/admin/backups/export', {
        method: 'POST', cache: 'no-store', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      });
      if (!response.ok) {
        if ([401, 403].includes(response.status)) {
          document.getElementById('controlContent').hidden = true;
          document.getElementById('controlLocked').hidden = false;
        }
        const data = await response.json().catch(() => ({}));
        throw Error(typeof data.detail === 'string' ? data.detail : 'Не удалось создать копию');
      }
      const blob = await response.blob();
      if (handle) {
        status.textContent = 'Сохраняем файл в выбранную папку…';
        writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
        writable = null;
        status.textContent = 'Копия сохранена в выбранную папку. Храните пароль отдельно. Открывать файл не нужно.';
      } else {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        status.textContent = 'Скачивание запущено. Нажмите Ctrl + J и «Показать в папке», чтобы найти копию. Храните пароль отдельно.';
      }
      form.reset();
    } catch (error) {
      if (writable) await writable.abort().catch(() => {});
      status.textContent = error.name === 'AbortError'
        ? 'Сохранение отменено. Новая копия не сохранена.'
        : 'Копия не сохранена. ' + error.message;
    } finally {
      for (const name of ['current_password', 'passphrase', 'confirm_passphrase']) form.elements[name].value = '';
      button.disabled = false;
    }
  });
})();
