const $ = (selector) => document.querySelector(selector);

const labels = {
  overall: "Общее впечатление",
  food: "Качество еды",
  service: "Обслуживание",
  cleanliness: "Чистота",
  value: "Соотношение цены и качества",
};

async function loadDashboard() {
  try {
    const response = await fetch("/v1/business/fregat", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Не удалось загрузить данные");

    $("#name").textContent = data.organization.name;
    $("#location").textContent = `${data.organization.branch} · ${data.organization.city}`;
    $("#score").textContent = Number(data.relyqo_score).toFixed(1);
    $("#ratings").textContent = data.rating_count;
    $("#visits").textContent = data.verified_visits;
    $("#metrics").innerHTML = Object.entries(data.metrics).map(([key, value]) => `
      <div class="metric-${key}">
        <div class="barTop"><span>${labels[key]}</span><b>${Number(value).toFixed(1)} / 100</b></div>
        <div class="track"><div class="fill" style="width:${Math.max(0, Math.min(100, value))}%"></div></div>
      </div>`).join("");
    $("#history").innerHTML = data.history.length
      ? data.history.map((item) => `<i style="height:${Math.max(4, item.score)}%" title="Score ${item.score}"></i>`).join("")
      : '<span class="empty">График появится после первой завершённой оценки гостя.</span>';
    $("#content").classList.remove("hidden");
  } catch (error) {
    $("#error").textContent = `Ошибка загрузки: ${error.message}`;
    $("#error").classList.remove("hidden");
  }
}

loadDashboard();
