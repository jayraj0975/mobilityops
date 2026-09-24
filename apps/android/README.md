# MobilityOps for Android

A native Android app (Java, Gradle) that shows the MobilityOps dashboard on a phone: a **Live**
tab (a labelled replay of held-out taxi days beside live Citi Bike and weather feeds), the
**Overview**, **Forecast** accuracy and next-day forecast, **Anomalies**, and **Settings** for the
server address and API key. It talks to your own MobilityOps server
([self-hosting](../../docs/SELF_HOSTING.md)); nothing is sent anywhere else.

It uses only platform networking (`HttpURLConnection`) and AndroidX/Material, so there is no
third-party network library to trust. Minimum Android 7.0 (API 24).

## Build

You need JDK 17 and the Android SDK (platform 34, build-tools 34). Gradle itself comes from the
wrapper.

```bash
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME=/path/to/android-sdk          # or put sdk.dir=... in local.properties
./gradlew assembleDebug                           # app/build/outputs/apk/debug/app-debug.apk
./gradlew testDebugUnitTest lintDebug             # 26 unit tests and Android lint
```

Install on a device or emulator: `adb install -r app/build/outputs/apk/debug/app-debug.apk`.

### Signed release build

A release APK must be signed with your own key. Create one and keep it out of the repository (`*.jks`
is ignored):

```bash
keytool -genkeypair -v -keystore ~/mobilityops-release.jks -alias mobilityops \
        -keyalg RSA -keysize 2048 -validity 10000
./gradlew assembleRelease
$ANDROID_HOME/build-tools/34.0.0/apksigner sign --ks ~/mobilityops-release.jks \
        --out app-release-signed.apk app/build/outputs/apk/release/app-release-unsigned.apk
$ANDROID_HOME/build-tools/34.0.0/apksigner verify app-release-signed.apk
```

## Connecting to the server

Open **Settings** on first launch. From the Android emulator the host computer is
`http://10.0.2.2:8000`; on a phone use the server's address on your network. Plain `http://` is
allowed (a home server rarely has a certificate); use the HTTPS setup in the self-hosting guide for
anything beyond your local network.

## What is tested

The stream client is tested against a real local server (delivery in order, the API key header,
reconnect after a dropped connection, the server's own refusal message, a malformed event not ending
the stream, backoff timing), together with the event parser, JSON models, formatting, address
normalisation and date arithmetic. Android lint reports no errors.
