"""Stable reason codes: historical labels never change with an object's category."""

# Each group has its own reasons. Shared codes retain their original meaning.
CATEGORY_REASONS = {
    "EDUCATION": [
        ("GOOD_TEACHING", "Понятное и качественное обучение", "Tushunarli va sifatli ta’lim"),
        ("SUPPORTIVE_TEACHERS", "Внимательные преподаватели", "E’tiborli o‘qituvchilar"),
        ("HELPFUL_ADMINISTRATION", "Администрация помогла", "Ma’muriyat yordam berdi"),
        ("GOOD_LEARNING_CONDITIONS", "Удобные условия обучения", "Qulay ta’lim sharoitlari"),
        ("CLEAR_REQUIREMENTS", "Понятные требования и правила", "Tushunarli talab va qoidalar"),
        ("POOR_TEACHING", "Недостаточное качество обучения", "Ta’lim sifati yetarli emas"),
        ("ADMINISTRATION_DELAYS", "Вопрос с администрацией не решён", "Ma’muriyat bilan masala hal bo‘lmadi"),
        ("POOR_LEARNING_CONDITIONS", "Проблемы с условиями обучения", "Ta’lim sharoitlarida muammolar"),
        ("UNCLEAR_REQUIREMENTS", "Непонятные требования", "Talablar tushunarsiz"),
    ],
    "FOOD": [
        ("TASTY_FOOD", "Вкусная еда", "Mazali taomlar"),
        ("FRESH_FOOD", "Свежие продукты", "Yangi mahsulotlar"),
        ("FOOD_ON_TIME", "Заказ принесли вовремя", "Buyurtma vaqtida keltirildi"),
        ("ATTENTIVE_WAITERS", "Внимательное обслуживание", "E’tiborli xizmat"),
        ("COMFORTABLE_DINING", "Чисто и уютно", "Toza va shinam"),
        ("FOOD_DISAPPOINTED", "Еда не понравилась", "Taomlar yoqmadi"),
        ("FOOD_WAIT", "Долго ждал заказ", "Buyurtmani uzoq kutdim"),
        ("WRONG_ORDER", "Ошибка в заказе или счёте", "Buyurtma yoki hisobda xato"),
    ],
    "HOTEL": [
        ("COMFORTABLE_ROOM", "Комфортный номер", "Qulay xona"),
        ("CLEAN_ROOM", "Чистый номер", "Toza xona"),
        ("HOTEL_HELPFUL_STAFF", "Персонал помог с вопросами", "Xodimlar masalalarni hal qilishda yordam berdi"),
        ("SMOOTH_CHECKIN", "Быстрое заселение", "Tez joylashish"),
        ("HOTEL_NOISE", "Шум мешал отдыху", "Shovqin dam olishga xalaqit berdi"),
        ("ROOM_PROBLEMS", "Проблемы в номере", "Xonada muammolar bor"),
        ("ROOM_NOT_AS_BOOKED", "Номер не соответствует бронированию", "Xona band qilinganiga mos emas"),
    ],
    "BEAUTY": [
        ("BEAUTY_GOOD_RESULT", "Результат понравился", "Natija yoqdi"),
        ("BEAUTY_CAREFUL_WORK", "Аккуратная работа мастера", "Ustaning puxta ishi"),
        ("BEAUTY_HYGIENE", "Чистые инструменты и рабочее место", "Toza asboblar va ish joyi"),
        ("BEAUTY_LISTENED", "Учли мои пожелания", "Istaklarim hisobga olindi"),
        ("BEAUTY_POOR_RESULT", "Результат не устроил", "Natija qoniqtirmadi"),
        ("BEAUTY_DELAY", "Приём начался с опозданием", "Qabul kech boshlandi"),
        ("BEAUTY_UNCLEAR_PRICE", "Цена оказалась неожиданной", "Narx kutilmagan bo‘ldi"),
    ],
    "HEALTH": [
        ("HEALTH_ATTENTION", "Внимательно выслушали", "Diqqat bilan tinglashdi"),
        ("HEALTH_EXPLAINED", "Понятно объяснили рекомендации", "Tavsiyalar tushunarli izohlandi"),
        ("HEALTH_RECEPTION", "Удобная запись и приём", "Qulay yozilish va qabul"),
        ("HEALTH_CLEAN", "Чистые помещения", "Toza xonalar"),
        ("HEALTH_WAIT", "Долгое ожидание приёма", "Qabulni uzoq kutdim"),
        ("HEALTH_UNCLEAR", "Не получил понятных объяснений", "Tushunarli izoh berilmadi"),
        ("HEALTH_COMMUNICATION", "Недостаточно внимания и уважения", "E’tibor va hurmat yetarli emas"),
    ],
    "RETAIL": [
        ("RETAIL_SELECTION", "Нашёл нужный товар", "Kerakli mahsulotni topdim"),
        ("RETAIL_HELP", "Помогли с выбором", "Tanlashda yordam berishdi"),
        ("RETAIL_QUALITY", "Товар хорошего качества", "Mahsulot sifati yaxshi"),
        ("RETAIL_CHECKOUT", "Быстро обслужили на кассе", "Kassada tez xizmat ko‘rsatildi"),
        ("RETAIL_PRICE_MISMATCH", "Цена на кассе отличается", "Kassadagi narx boshqacha"),
        ("RETAIL_DEFECT", "Проблема с качеством товара", "Mahsulot sifatida muammo"),
        ("RETAIL_RETURN", "Сложности с обменом или возвратом", "Almashtirish yoki qaytarishda qiyinchilik"),
    ],
    "AUTO_SERVICE": [
        ("AUTO_QUALITY", "Работу выполнили качественно", "Ish sifatli bajarildi"),
        ("AUTO_EXPLAINED", "Понятно объяснили работы", "Ishlar tushunarli izohlandi"),
        ("AUTO_ON_TIME", "Соблюли срок", "Muddatga rioya qilindi"),
        ("AUTO_PRICE", "Стоимость согласовали заранее", "Narx oldindan kelishildi"),
        ("AUTO_UNRESOLVED", "Проблема осталась", "Muammo hal bo‘lmadi"),
        ("AUTO_DELAY", "Задержали выполнение работ", "Ish bajarilishi kechikdi"),
        ("AUTO_EXTRA_COST", "Несогласованные расходы", "Kelishilmagan xarajatlar"),
    ],
    "PROFESSIONAL_SERVICE": [
        ("PRO_GOOD_RESULT", "Получил нужный результат", "Kerakli natijaga erishdim"),
        ("PRO_ON_TIME", "Работу завершили в срок", "Ish o‘z vaqtida tugatildi"),
        ("PRO_COMMUNICATION", "Были на связи и объясняли", "Aloqada bo‘lib, tushuntirishdi"),
        ("PRO_CLEAR_TERMS", "Понятные условия и стоимость", "Tushunarli shartlar va narx"),
        ("PRO_POOR_RESULT", "Результат не соответствует договорённости", "Natija kelishuvga mos emas"),
        ("PRO_DELAY", "Нарушены сроки", "Muddatlar buzildi"),
        ("PRO_NO_RESPONSE", "Сложно получить ответ", "Javob olish qiyin"),
    ],
    "ENTERTAINMENT": [
        ("FUN_PROGRAM", "Интересная программа", "Qiziqarli dastur"),
        ("FUN_ORGANIZATION", "Хорошая организация мероприятия", "Tadbir yaxshi tashkil etilgan"),
        ("FUN_COMFORT", "Удобно и комфортно", "Qulay va shinam"),
        ("FUN_STAFF", "Внимательные сотрудники", "E’tiborli xodimlar"),
        ("FUN_QUEUES", "Долгие очереди", "Uzun navbatlar"),
        ("FUN_EQUIPMENT", "Проблемы с оборудованием", "Jihozlarda muammolar"),
        ("FUN_NOT_AS_PROMISED", "Программа не соответствует описанию", "Dastur tavsifga mos emas"),
    ],
}


def reasons_for_group(group, all_reasons, generic_codes):
    codes = [row[0] for row in CATEGORY_REASONS.get(group, [])]
    if codes:
        codes.append("OTHER")
    else:
        codes = generic_codes
    return [{"code": code, "label": all_reasons[code][0], "label_uz": all_reasons[code][1]} for code in codes]
