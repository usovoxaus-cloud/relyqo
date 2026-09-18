RELYQO — ежедневные зашифрованные копии / kundalik shifrlangan nusxalar

1. В админке: Центр контроля → Состояние системы → Копии на Windows.
   Создайте ключ копирования, указав текущий пароль администратора.
2. Скачайте ZIP. В свойствах ZIP нажмите «Разблокировать», если Windows показывает
   такую отметку. Распакуйте архив целиком и откройте SETUP.cmd.
3. Вставьте ключ. Придумайте отдельный пароль копии (16–200 символов) и повторите его.
   Сохраните пароль отдельно от компьютера. Он нужен для восстановления.
4. Дождитесь первой успешной копии. Затем включится задание Windows:
   ежедневно в 19:00 и при входе в Windows. Компьютер должен быть включён,
   подключён к интернету, а вы — находиться в своей учётной записи Windows.
5. Файлы: Документы\RELYQO-Backups. Состояние: %LOCALAPPDATA%\RELYQO\Backup\last-status.txt.
   Проверьте дату сохранения в админке. Ключ действует 180 дней; после смены
   пароля администратора нужно выпустить новый ключ и повторить настройку.
6. Отключить: отозвать ключ в админке и отключить задание RELYQO Daily Backup
   в Планировщике заданий Windows. Старые копии сохраняются.

Секреты защищены Windows DPAPI: файл настроек читается только под вашей
учётной записью на этом компьютере. Пароль администратора не сохраняется.
Ключ даёт доступ только к выгрузке копии, а не к изменению данных.
Копии НЕ продлевают срок базы Render. Не удаляйте базу до переноса и проверки.
Храните дополнительную копию на другом устройстве. Старые копии не удаляются автоматически.

Восстановление выполняется администратором в ОТДЕЛЬНУЮ ПУСТУЮ базу:
python -m app.scripts.backup verify FILE.rqbackup
python -m app.scripts.backup restore FILE.rqbackup
Пароль передаётся через RELYQO_BACKUP_PASSPHRASE, адрес пустой базы —
RELYQO_RESTORE_DATABASE_URL. Проверка архива не заменяет пробное восстановление.

O‘zbekcha:
ZIP arxivini yuklab oling, to‘liq oching va SETUP.cmd faylini ishga tushiring.
Administrator panelidagi nusxalash kalitini kiriting. Nusxa uchun alohida
16–200 belgili parol tanlang va uni kompyuterdan tashqarida saqlang.
Birinchi nusxa saqlangach, Windows vazifasi har kuni 19:00 da va tizimga kirishda ishlaydi.
Kompyuter yoqilgan, internetga ulangan va Windows hisobingiz ochiq bo‘lishi kerak.
Fayllar: Documents\RELYQO-Backups. Kalit 180 kun amal qiladi.
Administrator paroli o‘zgarsa, yangi kalit yarating va sozlashni takrorlang.
Nusxalar Render bazasining amal qilish muddatini uzaytirmaydi.
Tiklash faqat alohida bo‘sh bazada bajariladi. Parolsiz nusxani tiklab bo‘lmaydi.
