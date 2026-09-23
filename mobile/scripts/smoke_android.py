"""Read-only, signed-APK smoke test on a disposable Android emulator."""
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = "uz.relyqo.mobile.preview"
OUTPUT = Path("mobile/smoke-output")
OUTPUT.mkdir(parents=True, exist_ok=True)


def adb(*args, binary=False):
    return subprocess.check_output(["adb", *args], text=not binary, timeout=25)


def snapshot():
    adb("shell", "uiautomator", "dump", "/sdcard/relyqo-ui.xml")
    xml = adb("shell", "cat", "/sdcard/relyqo-ui.xml")
    (OUTPUT / "last-ui.xml").write_text(xml)
    return ET.fromstring(xml)


def wait_label(label, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            root = snapshot()
            for node in root.iter("node"):
                if label in (node.get("text", ""), node.get("content-desc", "")):
                    return node
        except (ET.ParseError, subprocess.CalledProcessError):
            pass
        time.sleep(2)
    raise AssertionError(f"UI label missing: {label}")


def tap(label):
    node = wait_label(label)
    coords = list(map(int, re.findall(r"\d+", node.attrib["bounds"])))
    adb("shell", "input", "tap", str((coords[0] + coords[2]) // 2), str((coords[1] + coords[3]) // 2))


def shot(name):
    (OUTPUT / f"{name}.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))


def launch():
    adb("shell", "am", "start", "-W", "-n", f"{PACKAGE}/.MainActivity")


try:
    adb("install", "-r", "mobile/release/RELYQO-Android-preview.apk")
    flags = adb("shell", "dumpsys", "package", PACKAGE)
    assert "DEBUGGABLE" not in flags, "Release APK must not be debuggable"
    launch()
    wait_label("Найдите услугу в Узбекистане")
    shot("01-search")
    tap("QR")
    wait_label("Оцените посещение")
    wait_label("Разрешить камеру")
    shot("02-scanner-permission")
    tap("Вставить код вручную")
    wait_label("Подтвердить посещение")
    shot("03-manual-qr")
    tap("Закрыть")
    tap("Моё")
    wait_label("Войти в Мой RELYQO")
    shot("04-account")
    tap("Переключить язык на узбекский")
    wait_label("Mening")
    adb("shell", "am", "force-stop", PACKAGE)
    launch()
    wait_label("Qidiruv")
    wait_label("O‘zbekiston")
    shot("05-uzbek-persisted")
    adb("shell", "svc", "wifi", "disable")
    adb("shell", "svc", "data", "disable")
    adb("shell", "am", "force-stop", PACKAGE)
    launch()
    wait_label("Ulanib bo‘lmadi", timeout=20)
    wait_label("Qayta urinish")
    shot("06-offline")
    tap("QR")
    wait_label("Tashrifni baholang")
    print("PASS: Release launch, live search, scanner/manual fallback, account, persisted Uzbek, offline retry and offline scanner")
finally:
    try:
        shot("last-screen")
        (OUTPUT / "logcat.txt").write_text(adb("logcat", "-d", "-s", "AndroidRuntime:E", "ReactNativeJS:E"))
    finally:
        adb("shell", "svc", "wifi", "enable")
        adb("shell", "svc", "data", "enable")
