"""Exercise real release WebView history callbacks using isolated document fixtures."""
import subprocess
from pathlib import Path

output = Path("mobile/smoke-output/navigation")
output.mkdir(parents=True, exist_ok=True)
package = "uz.relyqo.mobile.preview"
subprocess.run(["adb", "shell", "am", "force-stop", package], check=True, timeout=30)
# Reset only the disposable emulator's language/preferences to Russian.
subprocess.run(["adb", "shell", "pm", "clear", package], check=True, timeout=30)
subprocess.run(["adb", "install", "-r", "mobile/navigation-test/RELYQO-navigation-test.apk"], check=True, timeout=60)
try:
    run = subprocess.run([
        "adb", "shell", "am", "instrument", "-w",
        "uz.relyqo.mobile.navigationtest/uz.relyqo.mobile.navigationtest.NavigationTest",
    ], capture_output=True, text=True, timeout=240)
    (output / "instrumentation.txt").write_text(run.stdout + run.stderr, encoding="utf-8")
    print(run.stdout, flush=True)
    assert run.returncode == 0 and "relyqo_navigation=passed" in run.stdout and "INSTRUMENTATION_CODE: -1" in run.stdout, "Native session navigation regression failed"
    print("PASS: Release native menu survives signed-in pages, history and layout changes; profile button and logout work")
finally:
    subprocess.run(["adb", "pull", f"/sdcard/Android/data/{package}/files/navigation-smoke/.", str(output)], timeout=30, check=False)
    logs = subprocess.run(["adb", "logcat", "-d", "-s", "AndroidRuntime:E", "ReactNativeJS:E"], capture_output=True, text=True, timeout=30)
    (output / "logcat.txt").write_text(logs.stdout, encoding="utf-8")
