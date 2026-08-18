# OtterWorks Web App

React 18 single-page application built with Vite, served by nginx in production,
wrapped by Capacitor to produce the native Android and iOS apps, and by Electron
to produce the desktop app - all from the same codebase.

## Development

```bash
npm ci
npm run dev        # Vite dev server on http://localhost:3000
```

API calls to `/api/v1/*` are proxied to the API gateway (default `http://localhost:8080`,
override with `API_GATEWAY_URL`) so the browser only ever talks same-origin. In production
the nginx config (`nginx/default.conf.template`) performs the same proxying; the gateway
URL is substituted from the `API_GATEWAY_URL` env var at container start.

| Command | Purpose |
|---------|---------|
| `npm run dev` | Dev server with HMR (port 3000) |
| `npm run build` | Type-check (`tsc --noEmit`) + production build to `dist/` |
| `npm run lint` | ESLint |
| `npm test` | Vitest unit tests |
| `npm run test:e2e` | Playwright e2e (expects the backend stack running) |
| `npm run test:bdd` | Cucumber BDD suite |

Build-time env vars (Vite): `VITE_COLLAB_WS_URL` (collab websocket URL, default
`ws://localhost:8085`, upgraded to `wss` when the page is served over https; native
defaults below), `VITE_API_BASE_URL` (native builds only, see below).

## Storage quotas

The dashboard shows a storage-usage bar comparing the user's usage against their
quota (`quotaBytes` from `GET /api/v1/auth/profile`, default 10 GiB). Usage is
computed client-side by paginating `/files` and summing file sizes. When an upload
is rejected with `413` and `{ "error": "quota_exceeded", ... }`, the upload dropzone
shows a dedicated "Storage full" error state instead of the generic upload failure.

## Docker

```bash
docker build -t otterworks-web-app .
docker run -p 3000:3000 -e API_GATEWAY_URL=http://api-gateway:8080 otterworks-web-app
```

The image is nginx (unprivileged, uid 101) serving `dist/` on port 3000 with an
`/api/health` endpoint and the `/api/v1` reverse proxy. When running with a read-only
root filesystem, mount a writable tmpfs at `/etc/nginx/conf.d` so the entrypoint can
render the config template (see `docker-compose.yml`).

## Mobile (Capacitor)

The `mobile/android/` and `mobile/ios/` directories are Capacitor platform projects
generated around the same `dist/` bundle (locations set via `android.path` / `ios.path`
in `capacitor.config.ts`). After changing web code:

```bash
npm run build && npx cap sync
npx cap run android   # build & launch on an Android emulator/device
npx cap open ios      # open in Xcode to run on an iOS simulator/device
```

Native builds cannot use the same-origin `/api/v1` proxy, so they call the API gateway
directly. Defaults target local development:

- Android emulator: `http://10.0.2.2:8080/api/v1` (host alias). Two gates make this work
  in **debug builds only**: `allowMixedContent` (WebView-level, `capacitor.config.ts`) and
  a debug-only network security config permitting cleartext to `10.0.2.2`
  (`mobile/android/app/src/debug/res/xml/network_security_config.xml`). Release builds
  keep cleartext disabled (`android:usesCleartextTraffic="false"`) and must use an https
  gateway.
- Override at build time for other environments, e.g.
  `VITE_API_BASE_URL=https://api.example.com/api/v1 npm run build && npx cap sync`
- iOS simulator: use `VITE_API_BASE_URL=http://localhost:8080/api/v1`

The API gateway's default CORS config allows the Capacitor WebView origins
(`https://localhost` on Android, `capacitor://localhost` on iOS).

The collab editor websocket also connects directly, with local-dev defaults of
`ws://10.0.2.2:8085` on Android and `ws://localhost:8085` on iOS (valid on the
simulator), so collaborative editing works on both simulators out of the box.
Override with `VITE_COLLAB_WS_URL` for physical devices or other environments, e.g.
`VITE_COLLAB_WS_URL=wss://collab.example.com npm run build && npx cap sync`.

Auth tokens are kept in `localStorage` (WebView-local). If shipping to stores, consider
moving them to `@capacitor/preferences` or a secure-storage plugin, and add real app
icons/splash screens with `@capacitor/assets`.

## Desktop (Electron)

The `desktop/` directory wraps the same `dist/` bundle in an Electron shell. Unlike the
native mobile builds, it keeps the web build's same-origin model: an embedded local
server (mirroring `nginx/default.conf.template`) serves the SPA with the index.html
fallback and reverse-proxies `/api/v1/*` - HTTP and WebSocket upgrades - to the API
gateway, so no `VITE_API_BASE_URL` rebuild is needed.

```bash
npm run build          # produce dist/ first (from frontend/client-app)
cd desktop
npm ci
npm start              # compile the main process and launch the app
```

| Command | Purpose |
|---------|---------|
| `npm start` | Build main process (`tsc`) + launch Electron |
| `npm test` | Smoke-test the embedded static/proxy server |
| `npm run smoke` | Boot the real app once and auto-quit (CI-friendly) |
| `npm run dist` | Package distributables into `desktop/release/` |
| `npm run icons` | Regenerate `assets/icon*.png` from `public/favicon.svg` |

Packaging targets: dmg/zip (macOS), NSIS (Windows), AppImage/deb (Linux), each built
for the host architecture by default. Icons are rendered from the otter favicon by
`scripts/make-icon.js` (runs inside Electron, so it works on all three OSes):
`icon-mac.png` sits on Apple's icon grid (transparent margins), while Windows/Linux
use the full-bleed `icon.png`; electron-builder derives `.icns`/`.ico`/png sets from
these at package time.

Runtime env vars (main process, not baked in at build time):

- `API_GATEWAY_URL` - gateway the `/api/v1` proxy targets (default `http://localhost:8080`)
- `OTTER_DESKTOP_PORT` - preferred local port (default `34117`; kept fixed so the
  `localStorage` auth tokens, scoped to the local origin, survive restarts)
- `ELECTRON_START_URL` - skip the embedded server and load this URL instead, e.g.
  `http://localhost:3000` to develop against the Vite dev server with HMR

The collab editor websocket connects directly (same as the web build): default
`ws://localhost:8085`, overridden with `VITE_COLLAB_WS_URL` when building `dist/`.

Note: launching Electron from an Electron-based IDE terminal exports
`ELECTRON_RUN_AS_NODE=1`, which breaks it; the npm scripts go through
`scripts/launch.js`, which strips that variable.
