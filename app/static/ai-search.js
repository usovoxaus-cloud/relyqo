/* AI interprets intent; city IDs and business records come from real sources. */
(() => {
  let cityRequest = 0, searchRequest = 0, searchTimer;
  window.relyqoCityChoices = new Map();
  const country = () => ratedFilterValue("#ratedCountry");
  const language = () => document.documentElement.lang === "uz" ? "uz" : "ru";
  const scope = () => [country(), ratedFilterValue("#ratedCity"), ratedFilterValue("#ratedCategory"), $("#catalogQuery").value.trim()].join("|");
  const status = text => {$("#citySearchStatus").textContent = text;};
  const normalize = value => String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

  async function jsonRequest(url, body) {
    const controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, body ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body), signal:controller.signal} : {signal:controller.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось выполнить поиск");
      return data;
    } finally { clearTimeout(deadline); }
  }

  window.relyqoLoadCities = async code => {
    const request = ++cityRequest;
    if (code === "ALL") {status(""); return;}
    status("Загружаем города выбранной страны…");
    try {
      let cities = window.relyqoCityChoices.get(code);
      if (!cities) cities = (await jsonRequest(`/v1/public/search/cities?country_code=${encodeURIComponent(code)}`)).items;
      if (request !== cityRequest || country() !== code) return;
      window.relyqoCityChoices.set(code, cities);
      updateRatedLocationFilters();
      status(`Города загружены: ${cities.length}. ИИ подбирает основные направления…`);
      const advice = await jsonRequest("/v1/public/search/cities/recommend", {country_code:code, language:language()});
      if (request !== cityRequest || country() !== code) return;
      const order = new Map(advice.recommended_ids.map((id,index) => [id,index]));
      window.relyqoCityChoices.set(code, [...cities].sort((a,b) => (order.get(a.id) ?? 999) - (order.get(b.id) ?? 999)));
      updateRatedLocationFilters();
      // Never overwrite status for a city search the user has already started.
      if (ratedFilterValue("#ratedCity") === "ALL") status(advice.ai_generated ? "Города загружены. ИИ показал основные города первыми — выберите нужный." : "Города загружены — выберите нужный.");
    } catch (_) {
      if (request === cityRequest && country() === code && ratedFilterValue("#ratedCity") === "ALL") status("Показаны доступные города. Расширить список сейчас не удалось.");
    }
  };

  window.relyqoCancelSearch = () => {++searchRequest; clearTimeout(searchTimer);};
  window.relyqoSearchOrganizations = () => {
    const chosenCity = ratedFilterValue("#ratedCity");
    if (country() === "ALL" || chosenCity === "ALL") return;
    const request = ++searchRequest, key = scope();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(request, key), 350);
  };

  async function runSearch(request, key) {
    const current = () => request === searchRequest && key === scope() && showRatedOnly;
    const body = {country_code:country(), city:ratedFilterValue("#ratedCity"), category:ratedFilterValue("#ratedCategory"), query:$("#catalogQuery").value.trim(), language:language()};
    status("ИИ уточняет запрос и ищет организации…");
    try {
      // Load the Places library without constructing a map or requesting GPS.
      const library = loadGooglePlaces();
      const plan = await jsonRequest("/v1/public/search/plan", body);
      if (!current()) return;
      if (!await library) throw new Error("Поиск новых организаций временно недоступен. Показаны найденные записи RELYQO.");
      if (!current()) return;
      const {Place} = await withDeadline(google.maps.importLibrary("places"), 12000);
      if (!current()) return;
      const center = {lat:plan.city.latitude, lng:plan.city.longitude};
      const requestBody = {
        textQuery:plan.text_query,
        fields:["id","displayName","location","formattedAddress","googleMapsURI","primaryType","addressComponents"],
        maxResultCount:12, language:body.language, region:body.country_code.toLowerCase(),
      };
      if (Number.isFinite(center.lat) && Number.isFinite(center.lng)) {
        const longitudeDelta = 0.23 / Math.max(0.3, Math.cos(center.lat * Math.PI / 180));
        requestBody.locationRestriction = {north:center.lat + 0.23, south:center.lat - 0.23, east:center.lng + longitudeDelta, west:center.lng - longitudeDelta};
      }
      const {places} = await withDeadline(Place.searchByText(requestBody), 12000);
      if (!current()) return;
      const aliases = new Set([plan.city.city, plan.city.label_ru, plan.city.label_uz, ...(plan.city.aliases || [])].map(normalize));
      lastCityPlaces = (places || []).map(place => externalPlaceItem(place, null)).filter(Boolean)
        .filter(item => item.country_code === body.country_code && aliases.has(normalize(item.city)))
        .map(item => ({...item, city:body.city, distance:null}));
      renderAll();
      status(plan.ai_generated ? `ИИ уточнил запрос. Найдено новых организаций: ${lastCityPlaces.length}.` : `Поиск выполнен. Найдено новых организаций: ${lastCityPlaces.length}. ИИ сейчас недоступен.`);
    } catch (error) {
      if (current()) status(error.message || "Поиск временно недоступен. Попробуйте ещё раз.");
    }
  }

  if (country() !== "ALL") window.relyqoLoadCities(country());
})();
