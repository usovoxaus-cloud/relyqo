package uz.relyqo.mobile.navigationtest;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.graphics.Bitmap;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebView;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.util.concurrent.atomic.AtomicReference;

/** Runs only as a separate test APK on a disposable emulator, never in the release. */
public final class NavigationTest extends Instrumentation {
    private Activity activity;
    private WebView web;
    private static final String ORIGIN = "https://relyqo.onrender.com";

    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            Intent intent = getTargetContext().getPackageManager().getLaunchIntentForPackage(getTargetContext().getPackageName());
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            activity = startActivitySync(intent);
            long deadline = SystemClock.uptimeMillis() + 30000;
            while (web == null && SystemClock.uptimeMillis() < deadline) {
                runOnMainSync(() -> web = findWeb(activity.getWindow().getDecorView()));
                SystemClock.sleep(200);
            }
            check(web != null, "WebView did not mount");
            // Wait for the live guest landing page, then replace it with isolated
            // document fixtures. No account, cookie, rating or production write.
            waitForGuestPage();
            fixture("/consumer?lang=ru", true, "");
            waitForTabs(true);
            shot("01-signed-in");
            for (int i = 0; i < 3; i++) {
                script("history.replaceState({position:" + i + "},'',location.href); true;");
                keepTabs(1200);
            }
            shot("02-history-replace");
            script("history.pushState({},'', '/community-rate?lang=ru&object_key=fixture'); true;");
            keepTabs(1500);
            shot("03-history-navigation");
            fixture("/community-rate?lang=ru&object_key=fixture", true, "page-community-rate");
            waitForTabs(true);
            keepTabs(1000);
            shot("04-community-rating");
            // Exercise the actual Pressable, not just the presence of its label.
            tapLabel("Профиль");
            waitForGuestPage(); // The real server correctly rejects our unsigned fixture session.
            waitForTabs(false);
            shot("05-profile-button-and-guest-guard");
            fixture("/nearby?lang=ru", true, "page-nearby"); // Missing optional directory markup.
            waitForTabs(true);
            script("history.replaceState({},''); true;");
            keepTabs(1500);
            shot("06-layout-adapter-failure");
            fixture("/welcome?lang=ru", false, "");
            waitForTabs(false);
            shot("07-explicit-logout");
            result.putString("relyqo_navigation", "passed");
            result.putString("coverage", "signed-in document; replaceState; pushState; community page; profile tap; layout failure; guest/logout");
            finish(Activity.RESULT_OK, result);
        } catch (Throwable failure) {
            try { shot("failure"); } catch (Throwable ignored) {}
            result.putString("relyqo_navigation", "failed");
            result.putString("failure", failure.toString());
            finish(Activity.RESULT_CANCELED, result);
        }
    }

    private void fixture(String path, boolean authenticated, String bodyClass) {
        String html = "<!doctype html><html lang='ru'><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
            + "<style>body{background:#071827;color:#fff;font:18px sans-serif;padding:24px}</style></head>"
            + "<body data-consumer-authenticated='" + authenticated + "' class='" + bodyClass + "'>"
            + "<h1>Navigation test fixture</h1><p>No user data or server session.</p></body></html>";
        runOnMainSync(() -> web.loadDataWithBaseURL(ORIGIN + path, html, "text/html", "UTF-8", null));
        SystemClock.sleep(500);
    }

    private void script(String code) { runOnMainSync(() -> web.evaluateJavascript(code, null)); }

    private void waitForGuestPage() {
        long deadline = SystemClock.uptimeMillis() + 90000;
        while (SystemClock.uptimeMillis() < deadline) {
            AtomicReference<Boolean> ready = new AtomicReference<>(false);
            runOnMainSync(() -> ready.set(web.getUrl() != null && web.getUrl().startsWith(ORIGIN + "/welcome") && web.getProgress() == 100));
            if (ready.get()) { SystemClock.sleep(500); return; }
            SystemClock.sleep(300);
        }
        throw new AssertionError("Guest page was not reached");
    }

    private boolean tabs() {
        AtomicReference<Boolean> visible = new AtomicReference<>(false);
        runOnMainSync(() -> {
            View root = activity.getWindow().getDecorView();
            visible.set(findLabel(root, "Найти") != null && findLabel(root, "Оценить") != null && findLabel(root, "Профиль") != null);
        });
        return visible.get();
    }

    private void waitForTabs(boolean expected) {
        long deadline = SystemClock.uptimeMillis() + 12000;
        while (SystemClock.uptimeMillis() < deadline) {
            if (tabs() == expected) { SystemClock.sleep(250); if (tabs() == expected) return; }
            SystemClock.sleep(100);
        }
        throw new AssertionError(expected ? "Native navigation missing" : "Guest navigation exposed");
    }

    private void keepTabs(long duration) {
        long deadline = SystemClock.uptimeMillis() + duration;
        while (SystemClock.uptimeMillis() < deadline) {
            check(tabs(), "Native navigation disappeared after a history update");
            SystemClock.sleep(100);
        }
    }

    private void tapLabel(String label) {
        int[] point = new int[2];
        runOnMainSync(() -> {
            View view = findLabel(activity.getWindow().getDecorView(), label);
            check(view != null, "Button missing: " + label);
            view.getLocationOnScreen(point);
            point[0] += view.getWidth() / 2; point[1] += view.getHeight() / 2;
        });
        long now = SystemClock.uptimeMillis();
        sendPointerSync(MotionEvent.obtain(now, now, MotionEvent.ACTION_DOWN, point[0], point[1], 0));
        sendPointerSync(MotionEvent.obtain(now, now + 80, MotionEvent.ACTION_UP, point[0], point[1], 0));
    }

    private static WebView findWeb(View view) {
        if (view instanceof WebView) return (WebView) view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup) view).getChildCount(); i++) {
            WebView found = findWeb(((ViewGroup) view).getChildAt(i));
            if (found != null) return found;
        }
        return null;
    }

    private static View findLabel(View view, String label) {
        if (!view.isShown()) return null;
        if (view instanceof TextView && label.contentEquals(((TextView) view).getText())) return view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup) view).getChildCount(); i++) {
            View found = findLabel(((ViewGroup) view).getChildAt(i), label);
            if (found != null) return found;
        }
        return null;
    }

    private void shot(String name) throws Exception {
        File folder = new File(getTargetContext().getExternalFilesDir(null), "navigation-smoke");
        check(folder.exists() || folder.mkdirs(), "Cannot create screenshot folder");
        Bitmap bitmap = getUiAutomation().takeScreenshot();
        check(bitmap != null, "Cannot capture emulator screenshot");
        try (FileOutputStream output = new FileOutputStream(new File(folder, name + ".png"))) {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, output);
        } finally { bitmap.recycle(); }
    }

    private static void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
