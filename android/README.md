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
http://REDACTED_IP:8000
```

`localhost` on a physical phone means the phone itself, not the development
machine.
