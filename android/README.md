# Jamarr Android POC

Stage 1 native Android prototype for Jamarr.

The app uses the existing API path documented in `../docs/api.md`:

1. `POST /api/auth/login`
2. `GET /api/search?q=<query>`
3. `GET /api/stream-url/{track_id}`
4. Media3 ExoPlayer playback of the returned stream URL

No backend or web routes are required for this prototype.

## Running

Open this `android/` directory in Android Studio, sync Gradle, then run the
`app` configuration on a USB-connected device.

For command-line installs, use the checked-in Gradle wrapper from this
directory:

```bash
./gradlew :app:installDebug
```

Use a Jamarr server URL reachable from the phone, for example:

```text
http://192.168.1.20:8000
```

`localhost` on a physical phone means the phone itself, not the development
machine.

## Testing in the car

The Stage 3 work adds an Android Auto browse tree backed by the same Media3
session. Before driving, validate against Android Studio's Desktop Head Unit
(DHU).

Prerequisites:

- Install **Android Auto Desktop Head Unit** via Android Studio →
  SDK Manager → SDK Tools.
- Install the Android Auto app on the phone, enable Developer Mode
  (Android Auto → tap the version banner 10×), then choose
  *Start head unit server*.
- USB-connect the phone with debugging authorised.

Run:

```bash
./scripts/dhu.sh
```

The script forwards the DHU socket, asks the phone to start the head-unit
server, and launches the DHU binary. Ctrl-C tears it all down.

In DHU, open the media app picker and pick **Jamarr** to load the browse tree.
If the token is missing or expired beyond refresh, the root shows a single
"Sign in on phone to use Jamarr" item.
