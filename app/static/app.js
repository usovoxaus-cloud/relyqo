const $ = (selector) => document.querySelector(selector);
let visitId;
let photoDataUrl = null;
let metrics = [];
const metricSets = {
  FOOD: ["Общее впечатление", "Качество еды / продукта", "Обслуживание", "Чистота", "Цена и ценность"],
  HOTEL: ["Общее впечатление", "Комфорт и состояние номера", "Обслуживание", "Чистота", "Цена и ценность"],
  BEAUTY: ["Результат", "Качество процедуры", "Мастер и обслуживание", "Гигиена", "Цена и ценность"],
  HEALTH: ["Общее впечатление", "Качество помощи", "Внимание персонала", "Гигиена и безопасность", "Цена и прозрачность"],
  ENTERTAINMENT: ["Впечатление", "Качество программы / развлечения", "Обслуживание", "Состояние места", "Цена и ценность"],
  RETAIL: ["Общее впечатление", "Ассортимент и качество товаров", "Обслуживание", "Порядок и удобство", "Цена и ценность"],
  AUTO_SERVICE: ["Общее впечатление", "Качество работы", "Сроки и обслуживание", "Аккуратность", "Цена и прозрачность"],
  PROFESSIONAL_SERVICE: ["Общее впечатление", "Качество результата", "Коммуникация и сервис", "Надёжность и порядок", "Цена и ценность"],
  OTHER: ["Общее впечатление", "Качество результата", "Удобство и сервис", "Состояние и порядок", "Цена и ценность"],
};
const foodCategories = new Set(["FOOD", "RESTAURANT", "CAFE", "COFFEE_SHOP", "BAKERY", "BAR", "FOOD_COURT"]);
const renderMetrics = (category = "OTHER") => {
  const group = foodCategories.has(category) ? "FOOD" : category;
  const labels = metricSets[group] || metricSets.OTHER;
  metrics = ["overall", "food", "service", "cleanliness", "value"].map((id, index) => [id, labels[index]]);
  $("#sliders").innerHTML = metrics.map(([id, label]) => `<div class="metric"><div class="metricTop"><label for="${id}">${label}</label><output id="${id}Out">8</output></div><input id="${id}" type="range" min="1" max="10" value="8" aria-label="${label}"></div>`).join("");
  metrics.forEach(([id]) => { $("#" + id).oninput = (event) => { $("#" + id + "Out").value = event.target.value; }; });
};
renderMetrics();

$("#photo").addEventListener("change", (event) => {
  const file = event.target.files[0];
  $("#rateError").textContent = "";
  if (!file) {
    photoDataUrl = null;
    $("#photoPreview").classList.add("hidden");
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    event.target.value = "";
    $("#rateError").textContent = "Фото должно быть не больше 5 МБ";
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    photoDataUrl = reader.result;
    $("#photoPreview").src = photoDataUrl;
    $("#photoPreview").classList.remove("hidden");
  };
  reader.readAsDataURL(file);
});

const api = async (url, body) => {
  const response = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Ошибка запроса");
  return data;
};

$("#verify").onclick = async () => {
  try {
    $("#scanError").textContent = "";
    const result = await api("/v1/visits/verify-token", { token: $("#token").value.trim() });
    visitId = result.visit_id;
    $("#place").textContent = result.organization.name;
    $("#branch").textContent = result.branch.name;
    renderMetrics(result.organization.category || "OTHER");
    $("#scan").classList.add("hidden");
    $("#rating").classList.remove("hidden");
  } catch (error) { $("#scanError").textContent = error.message; }
};

$("#demo").onclick = async () => {
  try {
    $("#scanError").textContent = "";
    const result = await api("/v1/demo/visit", {});
    location.href = result.visit_url;
  } catch (error) { $("#scanError").textContent = error.message; }
};

$("#submit").onclick = async () => {
  try {
    $("#rateError").textContent = "";
    const body = { visit_id: visitId, photo_data_url: photoDataUrl };
    metrics.forEach(([id]) => { body[id] = Number($("#" + id).value); });
    const result = await api("/v1/ratings", body);
    $("#score").textContent = result.relyqo_score.toFixed(1);
    $("#doneStatus").textContent = result.status === "PENDING_REVIEW" ? "ОЦЕНКА ПОЛУЧЕНА" : "ОЦЕНКА УЧТЕНА";
    $("#doneTitle").textContent = result.status === "PENDING_REVIEW" ? "Ожидает независимой проверки" : "RELYQO Score обновлён";
    $("#summary").textContent = result.status === "PENDING_REVIEW"
      ? "Оценка получена и направлена в RELYQO Owner Review. До решения она не влияет на Score."
      : `Ваша оценка ${result.ces_score.toFixed(1)} учтена. Всего подтверждённых оценок: ${result.rating_count}.`;
    $("#summary").textContent += result.saved_to_consumer_history
      ? " Verified-оценка сохранена в личной истории."
      : " Войдите в Мой RELYQO перед следующей QR-оценкой, чтобы сохранить её в личной истории.";
    if (result.photo_analysis) {
      $("#photoAnalysis").textContent = `AI-наблюдение по фото: ${result.photo_analysis}`;
      $("#photoAnalysis").classList.remove("hidden");
    } else if (result.photo_attached) {
      $("#photoAnalysis").textContent = "Фото сохранено как дополнительный материал оценки. AI-анализ временно недоступен.";
      $("#photoAnalysis").classList.remove("hidden");
    }
    $("#rating").classList.add("hidden");
    $("#done").classList.remove("hidden");
  } catch (error) { $("#rateError").textContent = error.message; }
};

const token = new URLSearchParams(location.search).get("token");
if (token) {
  $("#token").value = token;
  setTimeout(() => $("#verify").click(), 150);
}
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
