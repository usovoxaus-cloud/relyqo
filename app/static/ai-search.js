/* Source-backed Uzbekistan locations; AI improves intent without delaying live results. */
(() => {
  let searchRequest = 0, searchTimer;
  const plans = new Map();
  const language = () => document.documentElement.lang === "uz" ? "uz" : "ru";
  const scope = () => [ratedFilterValue("#ratedRegion"), ratedFilterValue("#ratedCity"), ratedFilterValue("#ratedCategory"), $("#catalogQuery").value.trim()].join("|");
  const status = text => {$("#citySearchStatus").textContent = text;};
  const normalize = value => String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

  async function jsonRequest(url, body, timeoutMs = 12000) {
    const controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, body ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body), signal:controller.signal} : {signal:controller.signal});
      if (!response.ok) throw new Error("Search unavailable");
      return await response.json();
    } finally { clearTimeout(deadline); }
  }

  function searchPlan(body) {
    const key = JSON.stringify(body), now = Date.now();
    const existing = plans.get(key);
    if (existing && existing.expires > now) return existing.promise;
    // Reuse both pending and successful plans when Find/Enter or filters repeat
    // the same intent. Failed plans remain retryable. Nothing is saved to disk.
    const entry = {expires:now + 30000};
    entry.promise = jsonRequest("/v1/public/search/plan", body, 30000).catch(() => null).then(plan => {
      if (plans.get(key) === entry) {
        if (plan?.ai_generated) entry.expires = Date.now() + 300000;
        else plans.delete(key);
      }
      return plan;
    });
    plans.set(key, entry);
    while (plans.size > 24) plans.delete(plans.keys().next().value);
    return entry.promise;
  }

  const locationsReady = jsonRequest("/static/uzbekistan.json?v=20260923").then(data => {
    window.relyqoUzbekistan = data;
    updateRatedLocationFilters();
    renderDirectoryGeography();
    return data;
  }).catch(() => {
    status("Не удалось загрузить города. Поиск по областям доступен — список городов появится после обновления страницы.");
    return {cities:[], regions:[...$("#ratedRegion").options].filter(row => row.value !== "ALL").map(row => ({code:row.value, label_ru:row.textContent, label_uz:row.textContent, aliases:[row.textContent]}))};
  });

  window.relyqoCancelSearch = () => {++searchRequest; clearTimeout(searchTimer); window.relyqoSearchPending = false;};
  window.relyqoSearchOrganizations = () => {
    const region = ratedFilterValue("#ratedRegion"), category = ratedFilterValue("#ratedCategory"), query = $("#catalogQuery").value.trim();
    if (region === "ALL" && category === "ALL" && !query) {status(""); return;}
    const request = ++searchRequest, key = scope();
    clearTimeout(searchTimer);
    window.relyqoSearchPending = true;
    status("Ищем организации в Узбекистане…");
    renderAll();
    searchTimer = setTimeout(() => runSearch(request, key), 350);
  };

  function inScope(place, item, city, region, data) {
    if (item.country_code !== "UZ") return false;
    const admin = normalize(addressPart(place, "administrative_area_level_1", "longText"));
    const recordedRegion = data.regions.find(row => [row.label_ru,row.label_uz,...row.aliases].some(alias => normalize(alias) === admin));
    if (region && recordedRegion && recordedRegion.code !== region.code) return false;
    if (city) {
      // Providers may report a district instead of a locality. Coordinates keep these real results.
      return distanceKm({lat:city.latitude,lng:city.longitude}, {lat:item.latitude,lng:item.longitude}) <= 25;
    }
    if (!region) return true;
    if (recordedRegion) return recordedRegion.code === region.code;
    const localities = data.cities.filter(row => [row.city,row.label_ru,row.label_uz,...row.aliases].some(alias => normalize(alias) === normalize(item.city)));
    return localities.length > 0 && localities.every(row => row.region_code === region.code);
  }

  async function runSearch(request, key) {
    const current = () => request === searchRequest && key === scope() && showRatedOnly;
    const body = {country_code:"UZ", region_code:ratedFilterValue("#ratedRegion") === "ALL" ? "" : ratedFilterValue("#ratedRegion"), city:ratedFilterValue("#ratedCity"), category:ratedFilterValue("#ratedCategory"), query:$("#catalogQuery").value.trim(), language:language()};
    // The planner and provider load in parallel; ordinary results never wait for the planner.
    const advice = body.query ? searchPlan(body) : Promise.resolve(null);
    const library = loadGooglePlaces();
    try {
      const data = await locationsReady;
      if (!current()) return;
      const region = data.regions.find(row => row.code === body.region_code);
      const city = data.cities.find(row => row.city === body.city && (!region || row.region_code === region.code));
      const location = city ? cityName(city) : region ? cityName(region) : "Узбекистан";
      const service = categoryNames[body.category] || "организации и услуги";
      const terms = body.query ? [body.query, body.category !== "ALL" ? service : ""].filter(Boolean).join(", ") : service;
      const plainQuery = `${terms}, ${location}, Узбекистан`;
      if (!await library) throw new Error("Places unavailable");
      if (!current()) return;
      const {Place} = await withDeadline(google.maps.importLibrary("places"), 12000);
      async function find(textQuery) {
        if (!current()) return [];
        const requestBody = {textQuery,fields:["id","displayName","location","formattedAddress","googleMapsURI","primaryType","addressComponents"],maxResultCount:20,language:body.language,region:"uz"};
        if (city) {
          const delta = 0.23 / Math.max(0.3, Math.cos(city.latitude * Math.PI / 180));
          requestBody.locationRestriction = {north:city.latitude+.23,south:city.latitude-.23,east:city.longitude+delta,west:city.longitude-delta};
        }
        const {places} = await withDeadline(Place.searchByText(requestBody), 12000);
        return (places || []).map(place => ({place,item:externalPlaceItem(place,null)}))
          .filter(({place,item}) => item && inScope(place,item,city,region,data))
          .map(({item}) => ({...item,distance:null}));
      }
      let found = await find(plainQuery);
      if (!current()) return;
      lastCityPlaces = found;
      window.relyqoSearchPending = Boolean(body.query && !found.length);
      renderAll();
      status(body.query
        ? (found.length ? `Найдено организаций: ${found.length}. ИИ уточняет запрос…` : "ИИ уточняет запрос. Поиск продолжается…")
        : found.length ? `Найдено организаций: ${found.length}.` : "По этому запросу организации не найдены. Попробуйте другую услугу или всю область.");
      const plan = await advice;
      if (!current()) return;
      const interpreted = plan?.interpreted_query ? ` Запрос: «${plan.interpreted_query}».` : "";
      if (plan?.ai_generated && plan.text_query && normalize(plan.text_query) !== normalize(plainQuery)) {
        // Keep the first results visible if enrichment fails or produces nothing.
        try {
          const refined = await find(plan.text_query);
          if (!current()) return;
          if (refined.length) {found = refined; lastCityPlaces = refined; renderAll();}
          status(refined.length ? `ИИ уточнил запрос.${interpreted} Найдено организаций: ${found.length}.` : "ИИ не нашёл дополнительных совпадений. Показаны результаты обычного поиска.");
        } catch (_) {if (current()) status("Показаны результаты поиска. Уточнение с ИИ сейчас недоступно.");}
      } else if (plan?.ai_generated) status(`ИИ уточнил запрос.${interpreted} Найдено организаций: ${found.length}.`);
      else if (body.query) status(found.length ? `Найдено организаций: ${found.length}. ИИ сейчас недоступен — обычный поиск работает.` : "Организации не найдены. Попробуйте короткий запрос, например «стоматология».");
    } catch (_) {
      if (current()) status("Поиск новых организаций временно недоступен. Показаны найденные записи RELYQO. Нажмите «Найти с ИИ», чтобы повторить.");
    } finally {
      if (current()) {window.relyqoSearchPending = false; renderAll();}
    }
  }
})();
