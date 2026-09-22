/* Public category labels only; no administrator statistics are exposed here. */
(() => {
  const selectors = 'select[name="category"],#manualCategory,#category,#serviceCategory,#ratedCategory';
  let items = [];
  window.relyqoCategoryLabel = code => items.find(item => item.code === code)?.label;
  window.relyqoCategoryGroup = code => items.find(item => item.code === code)?.group;
  window.relyqoApplyCategoryOptions = () => {
    for (const select of document.querySelectorAll(selectors)) {
      const existing = new Set([...select.options].map(option => option.value));
      for (const item of items) {
        if (existing.has(item.code)) continue;
        // The nearby map searches broad provider groups; the directory and
        // organization forms support every precise category.
        if (select.id === 'serviceCategory' && !item.custom && item.code !== item.group) continue;
        const option = document.createElement('option');
        option.value = item.code; option.textContent = item.label; select.append(option);
        existing.add(item.code);
      }
    }
  };
  const controller = new AbortController();
  const deadline = setTimeout(() => controller.abort(), 8000);
  window.relyqoCategoriesReady = fetch('/v1/public/service-categories', {cache:'no-store',signal:controller.signal})
    .then(response => {if (!response.ok) throw new Error('Categories unavailable'); return response.json();})
    .then(data => {items = data.items || []; window.relyqoApplyCategoryOptions(); return items;})
    .catch(() => [])
    .finally(() => clearTimeout(deadline));
  document.addEventListener('DOMContentLoaded', () => {
    window.relyqoApplyCategoryOptions();
    new MutationObserver(window.relyqoApplyCategoryOptions).observe(document.body, {childList:true,subtree:true});
  });
})();
