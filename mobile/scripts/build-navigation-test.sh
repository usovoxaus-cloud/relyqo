#!/usr/bin/env bash
set -euo pipefail
# Separate instrumentation APK. No test entry point is added to RELYQO itself.
build_tools="$(find "$ANDROID_HOME/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)"
android_jar="$ANDROID_HOME/platforms/android-36/android.jar"
output="navigation-test-build"
mkdir -p "$output/classes" "$output/dex" navigation-test
javac -source 8 -target 8 -encoding UTF-8 -classpath "$android_jar" -d "$output/classes" tests/native/NavigationTest.java
jar cf "$output/classes.jar" -C "$output/classes" .
"$build_tools/d8" --lib "$android_jar" --min-api 24 --output "$output/dex" "$output/classes.jar"
"$build_tools/aapt2" link -I "$android_jar" --manifest tests/native/AndroidManifest.xml -o "$output/unsigned.apk"
zip -j "$output/unsigned.apk" "$output/dex/classes.dex"
"$build_tools/zipalign" -f 4 "$output/unsigned.apk" "$output/aligned.apk"
"$build_tools/apksigner" sign --ks android/app/debug.keystore --ks-pass pass:android --key-pass pass:android \
  --out navigation-test/RELYQO-navigation-test.apk "$output/aligned.apk"
"$build_tools/apksigner" verify navigation-test/RELYQO-navigation-test.apk
