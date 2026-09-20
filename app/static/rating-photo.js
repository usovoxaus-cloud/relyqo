/* Both rating forms share the same attachment lifecycle. Never retain an old photo. */
(() => {
  window.relyqoRatingPhoto = ({input, preview, onError, onChange}) => {
    let version = 0, data = null, reading = false;
    const reset = () => {
      data = null;
      preview.removeAttribute('src');
      preview.classList.add('hidden');
    };
    input.addEventListener('change', () => {
      const current = ++version;
      const file = input.files[0];
      reset();
      reading = false;
      onChange?.();
      if (!file) return;
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
        input.value = '';
        onError('Выберите фотографию JPEG, PNG или WebP.');
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        input.value = '';
        onError('Фото должно быть не больше 5 МБ');
        return;
      }
      const reader = new FileReader();
      reading = true;
      reader.onload = () => {
        if (current !== version) return;
        reading = false;
        data = reader.result;
        preview.src = data;
        preview.classList.remove('hidden');
      };
      reader.onerror = reader.onabort = () => {
        if (current !== version) return;
        reading = false;
        reset();
        input.value = '';
        onError('Не удалось прочитать фото. Выберите его ещё раз.');
      };
      try { reader.readAsDataURL(file); } catch (_) { reader.onerror(); }
    });
    return {value() {
      if (reading) throw new Error('Подождите, фотография ещё загружается.');
      return data;
    }};
  };
})();
