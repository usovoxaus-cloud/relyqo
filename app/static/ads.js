(() => {
  const placements = ["TOP_BANNER", "CORNER"];
  const safeSession = {
    get(key) { try { return sessionStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { sessionStorage.setItem(key, value); } catch {} },
  };

  function choose(items, placement) {
    const candidates = items.filter(item => item.placement === placement && item.active);
    if (!candidates.length) return null;
    const seed = `${location.pathname}:${new Date().toISOString().slice(0, 10)}`;
    let hash = 0;
    for (const character of seed) hash = ((hash << 5) - hash + character.charCodeAt(0)) | 0;
    return candidates[Math.abs(hash) % candidates.length];
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function render(advertisement) {
    const dismissedKey = `relyqo-ad-dismissed:${advertisement.id}`;
    if (safeSession.get(dismissedKey)) return;
    const root = element("aside", `relyqo-ad ${advertisement.placement === "TOP_BANNER" ? "relyqo-ad-top" : "relyqo-ad-corner"}`);
    root.setAttribute("aria-label", `Реклама: ${advertisement.headline}`);
    const label = element("span", "relyqo-ad-label", "РЕКЛАМА");
    const copy = element("div", "relyqo-ad-copy");
    copy.append(
      element("span", "relyqo-ad-sponsor", advertisement.sponsor_name),
      element("strong", "relyqo-ad-title", advertisement.headline),
      element("span", "relyqo-ad-message", advertisement.message),
    );
    root.append(label, copy);
    if (advertisement.has_link && advertisement.click_url) {
      const action = element("a", "relyqo-ad-action", "Подробнее");
      action.href = advertisement.click_url;
      action.target = "_blank";
      action.rel = "noopener sponsored";
      root.append(action);
    }
    const close = element("button", "relyqo-ad-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Закрыть рекламу");
    close.addEventListener("click", () => {
      safeSession.set(dismissedKey, "1");
      root.remove();
    });
    root.append(close);
    if (advertisement.placement === "TOP_BANNER") document.body.prepend(root);
    else document.body.append(root);
    const impressionKey = `relyqo-ad-impression:${advertisement.id}`;
    if (!safeSession.get(impressionKey)) {
      safeSession.set(impressionKey, "1");
      fetch(`/v1/public/advertisements/${encodeURIComponent(advertisement.id)}/impression`, {
        method: "POST",
        keepalive: true,
        cache: "no-store",
      }).catch(() => {});
    }
  }

  async function load() {
    try {
      const response = await fetch("/v1/public/advertisements", { cache: "no-store" });
      if (!response.ok) return;
      const data = await response.json();
      for (const placement of placements) {
        const advertisement = choose(data.items || [], placement);
        if (advertisement) render(advertisement);
      }
    } catch {}
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load, { once: true });
  else load();
})();
