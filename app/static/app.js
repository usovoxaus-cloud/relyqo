const $ = (selector) => document.querySelector(selector);
let visitId;
const metrics = [
  ["overall", "Общее впечатление"],
  ["food", "Еда / продукт"],
  ["service", "Сервис"],
  ["cleanliness", "Чистота"],
  ["value", "Цена и ценность"],
];

$("#sliders").innerHTML = metrics.map(([id, label]) => `<div class="metric"><div class="metricTop"><label for="${id}">${label}</label><output id="${id}Out">8</output></div><input id="${id}" type="range" min="1" max="10" value="8" aria-label="${label}"></div>`).join("");
metrics.forEach(([id]) => { $("#" + id).oninput = (event) => { $("#" + id + "Out").value = event.target.value; }; });

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
    const body = { visit_id: visitId };
    metrics.forEach(([id]) => { body[id] = Number($("#" + id).value); });
    const result = await api("/v1/ratings", body);
    $("#score").textContent = result.relyqo_score.toFixed(1);
    $("#doneStatus").textContent = result.status === "PENDING_REVIEW" ? "ОЦЕНКА ПОЛУЧЕНА" : "ОЦЕНКА УЧТЕНА";
    $("#doneTitle").textContent = result.status === "PENDING_REVIEW" ? "Ожидает независимой проверки" : "RELYQO Score обновлён";
    $("#summary").textContent = result.status === "PENDING_REVIEW"
      ? "Оценка получена и направлена в RELYQO Owner Review. До решения она не влияет на Score."
      : `Ваша оценка ${result.ces_score.toFixed(1)} учтена. Всего подтверждённых оценок: ${result.rating_count}.`;
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
