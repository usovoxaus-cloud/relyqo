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


def tap_node(node):
    coords = list(map(int, re.findall(r"\d+", node.attrib["bounds"])))
    adb("shell", "input", "tap", str((coords[0] + coords[2]) // 2), str((coords[1] + coords[3]) // 2))


def tap(label):
    tap_node(wait_label(label))

def recover_online():
    deadline = time.monotonic() + 90
    retry_after = 0
    while time.monotonic() < deadline:
        root = snapshot()
        nodes = {node.get("text") or node.get("content-desc"): node for node in root.iter("node")}
        if "Profilingizni yarating" in nodes and "Ulanib bo‘lmadi" not in nodes and "Qayta urinish" not in nodes:
            return
        if "Qayta urinish" in nodes and time.monotonic() >= retry_after:
            tap_node(nodes["Qayta urinish"])
            retry_after = time.monotonic() + 5
        time.sleep(2)
    raise AssertionError("Entry form did not recover after enabling the network")

def shot(name):
    (OUTPUT / f"{name}.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))


def launch():
    adb("shell", "am", "start", "-W", "-n", f"{PACKAGE}/.MainActivity")


try:
    adb("install", "-r", "mobile/release/RELYQO-Android-preview.apk")
    flags = adb("shell", "dumpsys", "package", PACKAGE)
    assert "DEBUGGABLE" not in flags, "Release APK must not be debuggable"
    launch()
    wait_label("Добро пожаловать")
    wait_label("Создайте свой аккаунт")
    entry_xml = (OUTPUT / "last-ui.xml").read_text()
    assert 'text="Оценить"' not in entry_xml and 'text="Профиль"' not in entry_xml
    assert 'content-desc="Меню приложения"' not in entry_xml
    shot("01-registration-first")
    tap("Войти")
    wait_label("Рады видеть вас снова")
    wait_label("Email или имя пользователя")
    shot("02-separate-login")
    tap("Переключить язык на узбекский")
    wait_label("Xush kelibsiz")
    wait_label("Kirish")
    shot("03-uzbek-entry")
    adb("shell", "am", "force-stop", PACKAGE)
    launch()
    wait_label("Profilingizni yarating")
    wait_label("O‘zbekiston")
    shot("04-uzbek-persisted")
    adb("shell", "svc", "wifi", "disable")
    adb("shell", "svc", "data", "disable")
    adb("shell", "am", "force-stop", PACKAGE)
    launch()
    wait_label("Ulanib bo‘lmadi", timeout=20)
    wait_label("Qayta urinish")
    shot("05-offline")
    offline_xml = (OUTPUT / "last-ui.xml").read_text()
    assert 'text="Baholash"' not in offline_xml and 'text="Profil"' not in offline_xml
    # Retry must stay available while offline, without resetting the saved language.
    tap("Qayta urinish")
    wait_label("Ulanib bo‘lmadi", timeout=20)
    wait_label("O‘zbekiston")
    adb("shell", "svc", "wifi", "enable")
    adb("shell", "svc", "data", "enable")
    # Require the actual form and no error overlay, not just a visible retry button.
    recover_online()
    wait_label("O‘zbekiston")
    shot("06-online-again")
    # Also cover connectivity events while the app stays open.
    adb("shell", "svc", "wifi", "disable")
    adb("shell", "svc", "data", "disable")
    wait_label("Ulanib bo‘lmadi", timeout=20)
    wait_label("Qayta urinish")
    shot("07-network-lost-while-open")
    adb("shell", "svc", "wifi", "enable")
    adb("shell", "svc", "data", "enable")
    recover_online()
    wait_label("O‘zbekiston")
    shot("08-recovered-while-open")
    print("PASS: Release registration-first launch, separate login, guest navigation locked, persisted Uzbek, offline retry and restored connection")
finally:
    try:
        shot("last-screen")
        (OUTPUT / "connectivity.txt").write_text(adb("shell", "dumpsys", "connectivity"))
        (OUTPUT / "logcat.txt").write_text(adb("logcat", "-d", "-s", "AndroidRuntime:E", "ReactNativeJS:E"))
    finally:
        adb("shell", "svc", "wifi", "enable")
        adb("shell", "svc", "data", "enable")
