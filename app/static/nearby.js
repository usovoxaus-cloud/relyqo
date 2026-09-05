const $ = (selector) => document.querySelector(selector);

let lastPartners = [];
let lastManualPlaces = [];
let lastExternalPlaces = [];
let currentCenter = null;
let showFavoritesOnly = false;
let googleMap = null;
let googleMarkers = [];
let mapLoadPromise = null;
let remoteSearchQuery = "";
let remoteSearchIds = new Set();
let pendingManualLocation = null;
let pendingManualAction = "save";

const foodCategories = new Set([
  "RESTAURANT",
  "CAFE",
  "COFFEE_SHOP",
  "BAKERY",
  "BAR",
  "FOOD_COURT",
  "FOOD",
]);

const categoryNames = {
  FOOD: "Рестораны и кафе",
  RESTAURANT: "Ресторан",
  CAFE: "Кафе",
  COFFEE_SHOP: "Кофейня",
  BAKERY: "Пекарня",
  BAR: "Бар",
  FOOD_COURT: "Фуд-корт",
  HOTEL: "Гостиница",
  BEAUTY: "Красота и уход",
  HEALTH: "Здоровье",
  ENTERTAINMENT: "Развлечения",
  RETAIL: "Магазин",
  AUTO_SERVICE: "Автоуслуги",
  PROFESSIONAL_SERVICE: "Профессиональные услуги",
  EDUCATION: "Образование и университеты",
  OTHER: "Другая услуга",
};

const googlePlaceTypes = {
  ALL: [
    "restaurant", "cafe", "coffee_shop", "bakery", "bar", "food_court",
    "hotel", "motel", "hostel", "beauty_salon", "hair_salon", "barber_shop",
    "spa", "hospital", "medical_clinic", "doctor", "dentist", "pharmacy",
    "movie_theater", "amusement_park", "museum", "park", "shopping_mall",
    "supermarket", "clothing_store", "electronics_store", "car_repair",
    "car_wash", "gas_station", "lawyer", "real_estate_agency", "travel_agency",
    "gym", "school", "university", "educational_institution", "bank", "laundry", "veterinary_care",
  ],
  FOOD: [
    "restaurant", "cafe", "coffee_shop", "bakery", "bar", "food_court",
    "meal_takeaway", "dessert_shop", "ice_cream_shop", "tea_house", "pub",
  ],
  HOTEL: ["hotel", "motel", "hostel", "guest_house", "bed_and_breakfast", "resort_hotel", "lodging"],
  BEAUTY: ["beauty_salon", "hair_salon", "barber_shop", "nail_salon", "spa"],
  HEALTH: ["hospital", "medical_clinic", "doctor", "dentist", "pharmacy", "physiotherapist", "wellness_center"],
  ENTERTAINMENT: ["movie_theater", "amusement_park", "aquarium", "museum", "bowling_alley", "karaoke", "night_club", "event_venue", "park", "art_gallery"],
  RETAIL: ["shopping_mall", "store", "supermarket", "grocery_store", "clothing_store", "electronics_store", "home_goods_store", "book_store", "jewelry_store", "pet_store"],
  AUTO_SERVICE: ["car_dealer", "car_rental", "car_repair", "car_wash", "gas_station", "tire_shop", "auto_parts_store"],
  PROFESSIONAL_SERVICE: ["consultant", "lawyer", "real_estate_agency", "insurance_agency", "electrician", "plumber", "moving_company", "travel_agency"],
  EDUCATION: ["university", "educational_institution", "academic_department", "research_institute", "school", "secondary_school", "primary_school", "preschool", "library"],
  OTHER: ["gym", "bank", "post_office", "laundry", "veterinary_care", "pet_store", "tourist_attraction", "community_center"],
};

function showError(message) {
  $("#error").textContent = message;
  $("#error").classList.remove("hidden");
}

function clearError() {
  $("#error").classList.add("hidden");
}

function selectedRadius() {
  return Math.max(1, Math.min(50, Math.round(Number($("#radius").value) || 15)));
}

function selectedLimit() {
  const value = Number($("#resultLimit").value);
  return [20, 50, 100].includes(value) ? value : 20;
}

function categoryGroup(value) {
  if (foodCategories.has(String(value || "").toUpperCase())) return "FOOD";
  const normalized = String(value || "").toUpperCase();
  if (["HOTEL", "BEAUTY", "HEALTH", "ENTERTAINMENT", "RETAIL", "AUTO_SERVICE", "PROFESSIONAL_SERVICE", "EDUCATION"].includes(normalized)) return normalized;
  for (const [group, types] of Object.entries(googlePlaceTypes)) {
    if (group !== "ALL" && types.includes(String(value || "").toLowerCase())) return group;
  }
  return "OTHER";
}

function matchesCategory(item) {
  const selected = $("#serviceCategory").value;
  return selected === "ALL" || categoryGroup(item.category) === selected;
}

function readFavorites() {
  try {
    const value = JSON.parse(localStorage.getItem("relyqo_favorites_v1") || "[]");
    return new Set(Array.isArray(value) ? value : []);
  } catch {
    return new Set();
  }
}

function writeFavorites(items) {
  try {
    localStorage.setItem("relyqo_favorites_v1", JSON.stringify([...items]));
  } catch {
    showError("Браузер не разрешает сохранить избранное");
  }
}

function objectKey(item) {
  return item.kind === "partner" ? `relyqo:${item.branch_id}` : `manual:${item.id}`;
}

function sourceFor(item) {
  return item.kind === "partner" ? "RELYQO_PARTNER" : "MANUAL";
}

async function syncFavorite(item, saved) {
  if (item.kind === "external") return;
  try {
    await fetch("/v1/consumer/favorites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ object_key: objectKey(item), source: sourceFor(item), saved }),
      cache: "no-store",
    });
  } catch {}
}

function scoreFor(item) {
  return item.kind === "partner" && item.verified_partner ? Number(item.relyqo_score) || 0 : 0;
}

function reviewCount(item) {
  return item.kind === "partner" ? Number(item.verified_rating_count) || 0 : 0;
}

function sortRows(rows) {
  const mode = $("#sortMode").value;
  rows.sort((a, b) => {
    if (mode === "rating") return scoreFor(b) - scoreFor(a) || a.distance - b.distance;
    if (mode === "reviews") return reviewCount(b) - reviewCount(a) || a.distance - b.distance;
    if (mode === "name") return (a.title || "").localeCompare(b.title || "", "ru");
    return a.distance - b.distance;
  });
}

function normalizedName(value) {
  return String(value || "").toLocaleLowerCase("ru").replace(/[^\p{L}\p{N}]+/gu, "").trim();
}

function isAlreadyInRelyqo(external, internalRows) {
  const externalName = normalizedName(external.title);
  return internalRows.some((item) => {
    if (normalizedName(item.title) !== externalName) return false;
    return distanceKm(
      { lat: Number(external.latitude), lng: Number(external.longitude) },
      { lat: Number(item.latitude), lng: Number(item.longitude) },
    ) < 0.15;
  });
}

function viewRows() {
  const favorites = readFavorites();
  const query = $("#catalogQuery").value.trim().toLocaleLowerCase("ru");
  const internalRows = [
    ...lastPartners.map((item) => ({ kind: "partner", title: item.organization, distance: item.distance_km, ...item })),
    ...lastManualPlaces.map((item) => ({ kind: "manual", title: item.name, distance: item.distance_km, ...item })),
  ];
  let rows = [
    ...internalRows,
    ...lastExternalPlaces
      .map((item) => ({ kind: "external", title: item.name, ...item }))
      .filter((item) => !isAlreadyInRelyqo(item, internalRows)),
  ].filter(matchesCategory);
  if (query) {
    rows = rows.filter((item) => (
      item.kind === "external"
      && query === remoteSearchQuery
      && remoteSearchIds.has(item.id)
    ) || [item.title, item.address, item.city, item.description, categoryNames[item.category]]
      .filter(Boolean).join(" ").toLocaleLowerCase("ru").includes(query));
  }
  if (showFavoritesOnly) rows = rows.filter((item) => item.kind !== "external" && favorites.has(objectKey(item)));
  sortRows(rows);
  return rows.slice(0, selectedLimit());
}

function distanceKm(a, b) {
  const toRad = (value) => value * Math.PI / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const value = Math.sin(dLat / 2) ** 2
    + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 6371.0088 * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

function positionFor(item) {
  const radius = selectedRadius();
  const latKm = (Number(item.latitude) - currentCenter.lat) * 110.574;
  const lngKm = (Number(item.longitude) - currentCenter.lng) * 111.32 * Math.cos(currentCenter.lat * Math.PI / 180);
  return {
    x: Math.max(5, Math.min(95, 50 + lngKm / radius * 45)),
    y: Math.max(5, Math.min(95, 50 - latKm / radius * 45)),
  };
}

function focusPlace(id) {
  const card = document.getElementById(id);
  if (!card) return;
  card.classList.add("highlight");
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  setTimeout(() => card.classList.remove("highlight"), 1800);
}

async function loadGoogleMap() {
  if (googleMap) return true;
  if (mapLoadPromise) return mapLoadPromise;
  mapLoadPromise = (async () => {
    try {
      const response = await fetch("/v1/public/maps-config", { cache: "no-store" });
      const config = await response.json();
      if (!response.ok || !config.configured || !config.browser_key) return false;
      await new Promise((resolve, reject) => {
        window.relyqoGoogleMapReady = resolve;
        const script = document.createElement("script");
        script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(config.browser_key)}&libraries=places&callback=relyqoGoogleMapReady&v=weekly`;
        script.async = true;
        script.onerror = () => reject(new Error("Google Карта временно недоступна"));
        document.head.append(script);
      });
      $("#map").classList.add("googleReady");
      googleMap = new google.maps.Map($("#map"), {
        center: currentCenter,
        zoom: 13,
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: true,
      });
      return true;
    } catch {
      mapLoadPromise = null;
      return false;
    }
  })();
  return mapLoadPromise;
}

function googleZoom() {
  const radius = selectedRadius();
  return radius <= 2 ? 15 : radius <= 5 ? 14 : radius <= 10 ? 13 : radius <= 20 ? 12 : radius <= 35 ? 11 : 10;
}

function markerCardId(item) {
  return `place-${item.kind}-${item.branch_id || item.id}`;
}

function drawMap(rows) {
  if (!currentCenter) return;
  if (googleMap) {
    for (const marker of googleMarkers) marker.setMap(null);
    googleMarkers = [];
    googleMap.setCenter(currentCenter);
    googleMap.setZoom(googleZoom());
    googleMarkers.push(new google.maps.Marker({
      position: currentCenter,
      map: googleMap,
      title: "Вы находитесь здесь",
      label: { text: "●", color: "#0b2840", fontSize: "18px" },
    }));
    for (const item of rows) {
      const marker = new google.maps.Marker({
        position: { lat: Number(item.latitude), lng: Number(item.longitude) },
        map: googleMap,
        title: `${item.title} · ${Number(item.distance).toFixed(1)} км`,
        label: {
          text: item.kind === "partner" ? "R" : item.kind === "external" ? "G" : "+",
          color: "#05251d",
          fontWeight: "900",
        },
      });
      marker.addListener("click", () => focusPlace(markerCardId(item)));
      googleMarkers.push(marker);
    }
  } else {
    const root = $("#markers");
    root.replaceChildren();
    const you = document.createElement("span");
    you.className = "marker you";
    you.style.left = "50%";
    you.style.top = "50%";
    you.title = "Вы находитесь здесь";
    root.append(you);
    for (const item of rows) {
      const marker = document.createElement("button");
      const position = positionFor(item);
      marker.type = "button";
      marker.className = `marker ${item.kind === "manual" ? "manual" : item.kind === "external" ? "external" : ""}`;
      marker.style.left = `${position.x}%`;
      marker.style.top = `${position.y}%`;
      marker.textContent = item.kind === "partner" ? "R" : item.kind === "external" ? "G" : "+";
      marker.title = `${item.title} · ${Number(item.distance).toFixed(1)} км`;
      marker.addEventListener("click", () => focusPlace(markerCardId(item)));
      root.append(marker);
    }
    $("#centerLabel").textContent = `Центр: ${currentCenter.lat.toFixed(4)}, ${currentCenter.lng.toFixed(4)}`;
  }
  $("#mapCount").textContent = `${rows.length} мест`;
}

function profileUrl(item) {
  const params = new URLSearchParams({
    object_key: objectKey(item),
    source: sourceFor(item),
    name: item.title,
    address: item.address || "",
    category: categoryNames[item.category] || "Другая услуга",
    category_code: item.category || "OTHER",
    description: item.description || "",
    profile_status: item.profile_status || "",
    verified_score: item.relyqo_score || "",
    verified_count: item.verified_rating_count || "",
    branch_id: item.branch_id || "",
    city: item.city || "",
    country_code: item.country_code || "",
    latitude: item.latitude || "",
    longitude: item.longitude || "",
  });
  return `/place?${params}`;
}

function ratingUrl(item) {
  return `/community-rate?${new URLSearchParams({
    object_key: objectKey(item),
    source: sourceFor(item),
    name: item.title,
    address: item.address || "",
    category: item.category || "OTHER",
  })}`;
}

function criteriaNode(item) {
  const box = document.createElement("div");
  if (item.kind === "partner" && item.verified_metrics) {
    box.className = "criteria";
    const labels = { quality: "Качество", service: "Сервис", cleanliness: "Состояние", value: "Цена и ценность" };
    for (const key of Object.keys(labels)) {
      const cell = document.createElement("div");
      cell.className = "criterion";
      const label = document.createElement("span");
      label.textContent = labels[key];
      const score = document.createElement("b");
      score.textContent = `${Number(item.verified_metrics[key]).toFixed(1)}/100`;
      cell.append(label, score);
      box.append(cell);
    }
    return box;
  }
  box.className = "criteriaNote";
  box.textContent = item.kind === "external"
    ? "Google помогает найти адрес. Рейтинги Google не импортируются и не влияют на RELYQO."
    : "Отраслевые показатели появятся после оценок потребителей.";
  return box;
}

function mapLinkFor(item) {
  return item.mapsUri || `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${item.latitude},${item.longitude}`)}`;
}

function addMeta(meta, values) {
  for (const text of values) {
    const span = document.createElement("span");
    span.textContent = text;
    meta.append(span);
  }
}

function internalActions(item, favorites) {
  const actions = document.createElement("div");
  actions.className = "actions";
  const details = document.createElement("a");
  details.href = profileUrl(item);
  details.textContent = "Подробнее";
  const favorite = document.createElement("button");
  favorite.type = "button";
  favorite.className = `favoriteButton ${favorites.has(objectKey(item)) ? "saved" : ""}`;
  favorite.textContent = favorites.has(objectKey(item)) ? "♥ На моей карте" : "♡ На мою карту";
  favorite.addEventListener("click", () => {
    const savedItems = readFavorites();
    const saved = !savedItems.has(objectKey(item));
    if (saved) savedItems.add(objectKey(item));
    else savedItems.delete(objectKey(item));
    writeFavorites(savedItems);
    syncFavorite(item, saved);
    renderAll();
  });
  const rate = document.createElement("a");
  rate.className = "rateLink";
  rate.href = ratingUrl(item);
  rate.textContent = "Оценить в RELYQO";
  const mapLink = document.createElement("a");
  mapLink.href = mapLinkFor(item);
  mapLink.target = "_blank";
  mapLink.rel = "noopener";
  mapLink.textContent = "Открыть на карте";
  actions.append(details, favorite, rate, mapLink);
  if (item.kind === "partner" && item.verified_partner) {
    const verified = document.createElement("a");
    verified.href = "/";
    verified.textContent = "Verified только по QR";
    actions.append(verified);
  }
  return actions;
}

function openManualDialog(item = null, action = "save") {
  pendingManualAction = action;
  pendingManualLocation = item ? {
    lat: Number(item.latitude),
    lng: Number(item.longitude),
  } : null;
  $("#manualError").classList.add("hidden");
  if (item) {
    const category = item.category || "OTHER";
    $("#manualName").value = item.title || item.name || "";
    $("#manualCategory").value = category;
    $("#manualDescription").value = `${categoryNames[category] || "Организация"} — карточка подтверждена потребителем RELYQO для независимой оценки.`;
    $("#manualAddress").value = item.address || "";
    $("#manualCity").value = item.city || "Не указан";
    $("#manualCountry").value = item.country_code || "XX";
  } else {
    $("#manualForm").reset();
  }
  const submit = $("#manualForm").querySelector('[type="submit"]');
  submit.textContent = action === "rate" ? "Продолжить к оценке" : "Добавить в RELYQO";
  $("#manualDialog").showModal();
}

function externalActions(item) {
  const actions = document.createElement("div");
  actions.className = "actions";
  const rate = document.createElement("button");
  rate.type = "button";
  rate.className = "importButton rateLink";
  rate.textContent = "Оценить в RELYQO";
  rate.addEventListener("click", () => openManualDialog(item, "rate"));
  const save = document.createElement("button");
  save.type = "button";
  save.className = "importButton";
  save.textContent = "Сохранить в RELYQO";
  save.addEventListener("click", () => openManualDialog(item));
  const mapLink = document.createElement("a");
  mapLink.href = mapLinkFor(item);
  mapLink.target = "_blank";
  mapLink.rel = "noopener";
  mapLink.textContent = "Открыть на Google Карте";
  actions.append(rate, save, mapLink);
  return actions;
}

function renderList(rows) {
  const root = $("#results");
  root.replaceChildren();
  const favorites = readFavorites();
  if (!rows.length) {
    root.innerHTML = `<div class="empty">${showFavoritesOnly
      ? "На вашей личной карте пока нет объектов в выбранном радиусе."
      : "Организации не найдены. Измените радиус или сферу и повторите поиск."}</div>`;
    $("#listCount").textContent = "0 найдено";
    return;
  }
  for (const item of rows) {
    const card = document.createElement("section");
    card.id = markerCardId(item);
    card.className = `place ${item.kind === "partner" ? "partner" : item.kind === "external" ? "external" : ""}`;
    const top = document.createElement("div");
    top.className = "placeTop";
    const title = document.createElement("div");
    const badge = document.createElement("span");
    badge.className = `badge ${item.kind === "manual" ? "manual" : item.kind === "external" ? "external" : ""}`;
    badge.textContent = item.kind === "partner"
      ? (item.verified_partner ? "ПАРТНЁР RELYQO" : "ПРОФИЛЬ RELYQO")
      : item.kind === "manual" ? "ДОБАВЛЕНО ПОТРЕБИТЕЛЕМ" : "НАЙДЕНО · Google Maps";
    const heading = document.createElement("h2");
    heading.textContent = item.title;
    title.append(badge, heading);
    const score = document.createElement("div");
    score.className = "score";
    score.textContent = item.kind === "partner" && item.verified_partner
      ? `${Number(item.relyqo_score).toFixed(1)}/100`
      : item.kind === "external" ? "НА КАРТЕ" : "COMMUNITY";
    top.append(title, score);
    const address = document.createElement("p");
    address.className = "address";
    address.textContent = item.address || "Адрес не указан";
    const description = document.createElement("p");
    description.className = "description";
    description.textContent = item.description || `${categoryNames[item.category] || "Услуга"} рядом с вами.`;
    const meta = document.createElement("div");
    meta.className = "meta";
    addMeta(meta, [
      `${Number(item.distance).toFixed(1)} км`,
      categoryNames[item.category] || "Другая услуга",
      item.kind === "partner" ? `${item.verified_rating_count} Verified оценок`
        : item.kind === "manual" ? "Community объект" : "Данные показываются без сохранения",
    ]);
    card.append(
      top,
      address,
      description,
      meta,
      criteriaNode(item),
      item.kind === "external" ? externalActions(item) : internalActions(item, favorites),
    );
    root.append(card);
  }
  $("#listCount").textContent = `${rows.length} найдено`;
}

function updatePersonalMode() {
  const count = readFavorites().size;
  const button = $("#favoritesFilter");
  button.textContent = showFavoritesOnly ? `♥ Все места · ${count}` : `♡ Моя карта · ${count}`;
  button.classList.toggle("active", showFavoritesOnly);
}

function renderAll() {
  const rows = viewRows();
  drawMap(rows);
  renderList(rows);
  updatePersonalMode();
}

async function fetchNearby(url) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      latitude: currentCenter.lat,
      longitude: currentCenter.lng,
      radius_km: selectedRadius(),
      limit: 200,
    }),
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Не удалось загрузить каталог RELYQO");
  return data.items || [];
}

function searchCenters(center, radius, resultLimit) {
  const queryCount = resultLimit === 100 ? 5 : resultLimit === 50 ? 3 : 1;
  if (queryCount === 1) return [center];
  const centers = [center];
  const ringCount = queryCount - 1;
  const offsetKm = radius * 0.42;
  const longitudeScale = Math.max(20, 111.32 * Math.cos(center.lat * Math.PI / 180));
  for (let index = 0; index < ringCount; index += 1) {
    const angle = 2 * Math.PI * index / ringCount;
    centers.push({
      lat: center.lat + Math.cos(angle) * offsetKm / 110.574,
      lng: center.lng + Math.sin(angle) * offsetKm / longitudeScale,
    });
  }
  return centers;
}

function externalCategory(primaryType) {
  const group = categoryGroup(primaryType);
  if (group !== "FOOD") return group;
  const type = String(primaryType || "").toLowerCase();
  return {
    restaurant: "RESTAURANT",
    cafe: "CAFE",
    coffee_shop: "COFFEE_SHOP",
    bakery: "BAKERY",
    bar: "BAR",
    food_court: "FOOD_COURT",
  }[type] || "RESTAURANT";
}

function addressPart(place, type, property) {
  const component = (place.addressComponents || []).find((item) => (item.types || []).includes(type));
  return component ? component[property] || "" : "";
}

async function fetchExternalPlaces() {
  if (!window.google?.maps?.importLibrary) return [];
  const { Place, SearchNearbyRankPreference } = await google.maps.importLibrary("places");
  const found = new Map();
  const radius = selectedRadius();
  const limit = selectedLimit();
  const centers = searchCenters(currentCenter, radius, limit);
  const zoneRadius = centers.length === 1 ? radius : Math.max(1, radius * 0.72);
  const selected = $("#serviceCategory").value || "ALL";
  for (const center of centers) {
    const request = {
      fields: ["displayName", "location", "formattedAddress", "googleMapsURI", "primaryType", "addressComponents"],
      locationRestriction: { center, radius: Math.min(50000, zoneRadius * 1000) },
      maxResultCount: 20,
      rankPreference: SearchNearbyRankPreference.POPULARITY,
      language: (navigator.language || "ru").split("-")[0],
    };
    if (selected !== "ALL") request.includedPrimaryTypes = googlePlaceTypes[selected] || [];
    const { places } = await Place.searchNearby(request);
    for (const place of places || []) {
      if (!place.location || !place.id || found.has(place.id)) continue;
      const coordinates = { lat: place.location.lat(), lng: place.location.lng() };
      const distance = distanceKm(currentCenter, coordinates);
      if (distance > radius) continue;
      const category = externalCategory(place.primaryType);
      found.set(place.id, {
        id: place.id,
        name: place.displayName || "Организация",
        address: place.formattedAddress || "Адрес на Google Карте",
        city: addressPart(place, "locality", "longText")
          || addressPart(place, "administrative_area_level_2", "longText")
          || addressPart(place, "administrative_area_level_1", "longText")
          || "Не указан",
        country_code: addressPart(place, "country", "shortText").toUpperCase() || "XX",
        category,
        primaryType: place.primaryType || "",
        description: `${categoryNames[category] || "Организация"}, найденная в Google Maps. Внешние рейтинги не используются RELYQO.`,
        latitude: coordinates.lat,
        longitude: coordinates.lng,
        distance,
        mapsUri: place.googleMapsURI || "",
      });
    }
  }
  return [...found.values()].sort((a, b) => a.distance - b.distance).slice(0, limit);
}

function externalPlaceItem(place) {
  if (!place.location || !place.id) return null;
  const coordinates = { lat: place.location.lat(), lng: place.location.lng() };
  const category = externalCategory(place.primaryType);
  return {
    id: place.id,
    name: place.displayName || "Организация",
    address: place.formattedAddress || "Адрес на Google Карте",
    city: addressPart(place, "locality", "longText")
      || addressPart(place, "administrative_area_level_2", "longText")
      || addressPart(place, "administrative_area_level_1", "longText")
      || "Не указан",
    country_code: addressPart(place, "country", "shortText").toUpperCase() || "XX",
    category,
    primaryType: place.primaryType || "",
    description: `${categoryNames[category] || "Организация"}, найденная в Google Maps. Внешние рейтинги не используются RELYQO.`,
    latitude: coordinates.lat,
    longitude: coordinates.lng,
    distance: distanceKm(currentCenter, coordinates),
    mapsUri: place.googleMapsURI || "",
  };
}

async function searchCatalog() {
  const input = $("#catalogQuery");
  const query = input.value.trim();
  if (!query) {
    remoteSearchQuery = "";
    remoteSearchIds = new Set();
    if (!currentCenter) await locate();
    else await refreshCatalog();
    return;
  }
  if (!currentCenter) await locate();
  if (!currentCenter) return;
  clearError();
  const button = $("#catalogSearchButton");
  button.disabled = true;
  $("#status").textContent = `Ищем «${query}»…`;
  try {
    const mapReady = await loadGoogleMap();
    if (!mapReady) throw new Error("Google Places сейчас недоступен");
    const { Place, SearchByTextRankPreference } = await google.maps.importLibrary("places");
    const { places } = await Place.searchByText({
      textQuery: query,
      fields: ["displayName", "location", "formattedAddress", "googleMapsURI", "primaryType", "addressComponents"],
      locationBias: { center: currentCenter, radius: selectedRadius() * 1000 },
      maxResultCount: Math.min(20, selectedLimit()),
      rankPreference: SearchByTextRankPreference.RELEVANCE,
      language: (navigator.language || "ru").split("-")[0],
    });
    const found = (places || []).map(externalPlaceItem).filter(Boolean)
      .filter((item) => item.distance <= selectedRadius());
    lastExternalPlaces = found;
    remoteSearchQuery = query.toLocaleLowerCase("ru");
    remoteSearchIds = new Set(found.map((item) => item.id));
    renderAll();
    $("#status").textContent = found.length
      ? `По запросу «${query}» найдено: ${found.length}.`
      : `По запросу «${query}» в радиусе ${selectedRadius()} км ничего не найдено.`;
  } catch (error) {
    remoteSearchQuery = "";
    remoteSearchIds = new Set();
    renderAll();
    showError(`Поиск по названию временно недоступен: ${error.message || "повторите позже"}`);
    $("#status").textContent = "Поиск не выполнен";
  } finally {
    button.disabled = false;
  }
}

async function refreshCatalog() {
  if (!currentCenter) return;
  clearError();
  $("#mapRadius").textContent = selectedRadius();
  $("#status").textContent = "Ищем организации рядом…";
  const mapReady = await loadGoogleMap();
  [lastPartners, lastManualPlaces] = await Promise.all([
    fetchNearby("/v1/public/branches/nearby"),
    fetchNearby("/v1/public/manual-places/nearby"),
  ]);
  lastExternalPlaces = [];
  if (mapReady) {
    try {
      lastExternalPlaces = await fetchExternalPlaces();
    } catch (error) {
      showError(`Google Places пока не ответил: ${error.message || "проверьте доступ Places API (New)"}. Объекты RELYQO показаны ниже.`);
    }
  } else {
    showError("Google Карта не загрузилась. Объекты собственного каталога RELYQO всё равно показаны ниже.");
  }
  renderAll();
  $("#status").textContent = `Готово: ${lastPartners.length + lastManualPlaces.length} объектов RELYQO и ${lastExternalPlaces.length} организаций найдено на карте.`;
}

async function locate() {
  clearError();
  const button = $("#locate");
  button.disabled = true;
  $("#status").textContent = "Определяем местоположение…";
  try {
    if (!navigator.geolocation) throw new Error("Ваш браузер не поддерживает геолокацию");
    const position = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(
      resolve,
      reject,
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 300000 },
    ));
    currentCenter = { lat: position.coords.latitude, lng: position.coords.longitude };
    $("#addPlace").disabled = false;
    $("#radius").value = selectedRadius();
    await refreshCatalog();
  } catch (error) {
    showError(error.code === 1
      ? "Доступ к геолокации запрещён. Разрешите его в настройках браузера и нажмите «Найти организации»."
      : error.message || "Не удалось определить местоположение");
    $("#status").textContent = "Поиск не выполнен";
  } finally {
    button.disabled = false;
  }
}

$("#locate").addEventListener("click", locate);
$("#addPlace").addEventListener("click", () => openManualDialog());
$("#cancelManual").addEventListener("click", () => {
  pendingManualAction = "save";
  pendingManualLocation = null;
  $("#manualDialog").close();
});
$("#favoritesFilter").addEventListener("click", () => {
  showFavoritesOnly = !showFavoritesOnly;
  renderAll();
});
$("#sortMode").addEventListener("change", renderAll);
$("#catalogQuery").addEventListener("input", renderAll);
$("#catalogSearchButton").addEventListener("click", searchCatalog);
$("#catalogQuery").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchCatalog();
  }
});
$("#serviceCategory").addEventListener("change", () => currentCenter ? refreshCatalog() : renderAll());
$("#resultLimit").addEventListener("change", () => currentCenter ? refreshCatalog() : renderAll());
$("#radius").addEventListener("change", () => currentCenter ? refreshCatalog() : renderAll());

document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
    event.preventDefault();
    $("#catalogQuery").focus();
  }
  if (event.key === "Escape" && document.activeElement === $("#catalogQuery")) {
    $("#catalogQuery").value = "";
    $("#catalogQuery").blur();
    renderAll();
  }
});

$("#manualForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const locationForPlace = pendingManualLocation || currentCenter;
  if (!locationForPlace) return;
  const submit = event.submitter;
  submit.disabled = true;
  $("#manualError").classList.add("hidden");
  const body = {
    name: $("#manualName").value,
    category: $("#manualCategory").value,
    description: $("#manualDescription").value,
    address: $("#manualAddress").value,
    city: $("#manualCity").value,
    country_code: $("#manualCountry").value.toUpperCase(),
    latitude: locationForPlace.lat,
    longitude: locationForPlace.lng,
  };
  try {
    const response = await fetch("/v1/public/manual-places", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Не удалось добавить место");
    data.item.distance_km = distanceKm(currentCenter, {
      lat: Number(data.item.latitude),
      lng: Number(data.item.longitude),
    });
    lastManualPlaces = [data.item, ...lastManualPlaces.filter((item) => item.id !== data.item.id)];
    renderAll();
    $("#manualDialog").close();
    $("#manualForm").reset();
    $("#status").textContent = `${data.item.name} добавлено в каталог RELYQO.`;
    if (pendingManualAction === "rate") {
      const addedItem = { kind: "manual", title: data.item.name, distance: data.item.distance_km, ...data.item };
      location.href = ratingUrl(addedItem);
      return;
    }
    pendingManualLocation = null;
  } catch (error) {
    $("#manualError").textContent = error.message;
    $("#manualError").classList.remove("hidden");
  } finally {
    submit.disabled = false;
  }
});

updatePersonalMode();
locate();
