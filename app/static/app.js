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
  EDUCATION: ["Общее впечатление", "Качество обучения", "Преподаватели и поддержка", "Инфраструктура и условия", "Стоимость и результат"],
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

let cameraStream = null;
let scanTimer = null;
let qrDetector = null;
const qrCanvas = document.createElement("canvas");
const qrContext = qrCanvas.getContext("2d", { willReadFrequently: true });

const stopCamera = () => {
  if (scanTimer) window.clearTimeout(scanTimer);
  scanTimer = null;
  if (cameraStream) cameraStream.getTracks().forEach((track) => track.stop());
  cameraStream = null;
  $("#cameraPreview").srcObject = null;
  $("#cameraBox").classList.add("hidden");
};

const readRelyqoToken = (rawValue) => {
  const value = String(rawValue || "").trim();
  if (!value) throw new Error("QR-код пустой");
  if (/^https?:\/\//i.test(value)) {
    const url = new URL(value);
    const scannedToken = url.searchParams.get("token");
    if (!scannedToken) throw new Error("Это не QR посещения RELYQO");
    return scannedToken;
  }
  return value;
};

const acceptScannedQr = (rawValue) => {
  const scannedToken = readRelyqoToken(rawValue);
  $("#token").value = scannedToken;
  $("#scanStatus").textContent = "QR распознан. Подтверждаем посещение…";
  stopCamera();
  $("#verify").click();
};

const prepareQrReader = async () => {
  if (!qrDetector && "BarcodeDetector" in window) {
    try {
      const formats = BarcodeDetector.getSupportedFormats
        ? await BarcodeDetector.getSupportedFormats()
        : ["qr_code"];
      if (formats.includes("qr_code")) qrDetector = new BarcodeDetector({ formats: ["qr_code"] });
    } catch (_) {
      qrDetector = null;
    }
  }
  if (!qrDetector && typeof window.jsQR !== "function") {
    throw new Error("Модуль QR не загрузился. Проверьте интернет и обновите страницу.");
  }
};

const detectQr = async (source) => {
  if (qrDetector) {
    try {
      const codes = await qrDetector.detect(source);
      if (codes.length) return codes[0].rawValue;
    } catch (_) {
      qrDetector = null;
    }
  }
  if (typeof window.jsQR !== "function" || !qrContext) return null;
  const sourceWidth = source.videoWidth || source.naturalWidth || source.width;
  const sourceHeight = source.videoHeight || source.naturalHeight || source.height;
  if (!sourceWidth || !sourceHeight) return null;
  const scale = Math.min(1, 1280 / sourceWidth);
  qrCanvas.width = Math.max(1, Math.round(sourceWidth * scale));
  qrCanvas.height = Math.max(1, Math.round(sourceHeight * scale));
  qrContext.drawImage(source, 0, 0, qrCanvas.width, qrCanvas.height);
  const imageData = qrContext.getImageData(0, 0, qrCanvas.width, qrCanvas.height);
  const code = window.jsQR(imageData.data, imageData.width, imageData.height, {
    inversionAttempts: "attemptBoth",
  });
  return code?.data || null;
};

const scanVideoFrame = async () => {
  if (!cameraStream) return;
  const video = $("#cameraPreview");
  try {
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      const rawValue = await detectQr(video);
      if (rawValue) {
        acceptScannedQr(rawValue);
        return;
      }
    }
  } catch (error) {
    $("#scanError").textContent = `Не удалось прочитать QR: ${error.message}`;
  }
  scanTimer = window.setTimeout(scanVideoFrame, 220);
};

const cameraErrorMessage = (error) => {
  if (error.name === "NotAllowedError" || error.name === "SecurityError") {
    return "Доступ к камере запрещён. Разрешите камеру для relyqo.onrender.com в настройках браузера.";
  }
  if (error.name === "NotFoundError") return "Камера на этом устройстве не найдена.";
  if (error.name === "NotReadableError") return "Камера занята другим приложением. Закройте его и попробуйте снова.";
  return error.message;
};

$("#startCamera").onclick = async () => {
  try {
    $("#scanError").textContent = "";
    $("#scanStatus").textContent = "Запрашиваем разрешение на камеру…";
    await prepareQrReader();
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("Камера недоступна в этом браузере");
    stopCamera();
    cameraStream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: "environment" } },
    });
    const video = $("#cameraPreview");
    video.srcObject = cameraStream;
    $("#cameraBox").classList.remove("hidden");
    await video.play();
    $("#scanStatus").textContent = "Наведите камеру на QR-код RELYQO";
    scanVideoFrame();
  } catch (error) {
    stopCamera();
    $("#scanStatus").textContent = "";
    $("#scanError").textContent = cameraErrorMessage(error);
  }
};

$("#stopCamera").onclick = () => {
  stopCamera();
  $("#scanStatus").textContent = "Сканирование остановлено";
};

$("#qrImage").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    $("#scanError").textContent = "";
    $("#scanStatus").textContent = "Читаем QR с фотографии…";
    await prepareQrReader();
    const image = await createImageBitmap(file);
    const rawValue = await detectQr(image);
    image.close();
    if (!rawValue) throw new Error("На фотографии QR-код не найден");
    acceptScannedQr(rawValue);
  } catch (error) {
    $("#scanStatus").textContent = "";
    $("#scanError").textContent = error.message;
  } finally {
    event.target.value = "";
  }
});

window.addEventListener("pagehide", stopCamera);

$("#verify").onclick = async () => {
  try {
    $("#scanError").textContent = "";
    $("#scanStatus").textContent = "";
    stopCamera();
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
