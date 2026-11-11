import { app, BrowserWindow, dialog, shell } from "electron";
import path from "node:path";
import fs from "node:fs";
import { startAppServer, AppServer } from "./server";

// OtterWorks desktop shell. Serves the client-app web build (`../dist`) from an
// embedded local server that also proxies /api/v1/* to the API gateway - the
// same same-origin model used by the Vite dev server and the production nginx
// container - then points a BrowserWindow at it.
//
// Environment:
//   API_GATEWAY_URL     gateway the /api/v1 proxy targets (default http://localhost:8080)
//   OTTER_DESKTOP_PORT  preferred local port (default 34117; fixed so
//                       the HttpOnly refresh-token cookie survives restarts)
//   ELECTRON_START_URL  skip the embedded server and load this URL instead
//                       (e.g. http://localhost:3000 for Vite HMR development)

const GATEWAY_URL = process.env.API_GATEWAY_URL || "http://localhost:8080";
const PREFERRED_PORT = Number(process.env.OTTER_DESKTOP_PORT) || 34117;
const START_URL = process.env.ELECTRON_START_URL;
const SMOKE_TEST = process.argv.includes("--smoke-test");

// Otter icons for unpackaged (npm start) runs; packaged builds get the platform
// formats electron-builder derives from assets/ at build time. Windows/Linux
// icons are full-bleed, while the macOS Dock uses the Apple-grid variant.
const DEV_ICON = path.resolve(__dirname, "..", "assets", "icon.png");
const DEV_DOCK_ICON = path.resolve(__dirname, "..", "assets", "icon-mac.png");
const HAS_DEV_ICON = !app.isPackaged && fs.existsSync(DEV_ICON);

let appServer: AppServer | null = null;
let appOrigin: string | null = null;

function resolveWebRoot(): string {
  // Packaged: dist/ is bundled via extraResources; dev: use the sibling web build.
  const webRoot = app.isPackaged
    ? path.join(process.resourcesPath, "dist")
    : path.resolve(__dirname, "..", "..", "dist");
  if (!fs.existsSync(path.join(webRoot, "index.html"))) {
    throw new Error(
      `Web build not found at ${webRoot}. Run \`npm run build\` in frontend/client-app first.`
    );
  }
  return webRoot;
}

function createWindow(url: string): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    title: "OtterWorks",
    ...(HAS_DEV_ICON ? { icon: DEV_ICON } : {}),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Keep the window on the app origin; hand anything external to the OS browser.
  win.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:/i.test(target)) shell.openExternal(target);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, target) => {
    if (appOrigin && new URL(target).origin !== appOrigin) {
      event.preventDefault();
      if (/^https?:/i.test(target)) shell.openExternal(target);
    }
  });

  if (SMOKE_TEST) {
    win.webContents.once("did-finish-load", () => {
      console.log(`[desktop] smoke test ok: loaded ${url}`);
      app.exit(0);
    });
    win.webContents.once("did-fail-load", (_e, code, desc) => {
      console.error(`[desktop] smoke test failed: ${code} ${desc}`);
      app.exit(1);
    });
    setTimeout(() => {
      console.error("[desktop] smoke test timed out");
      app.exit(1);
    }, 20_000);
  }

  win.loadURL(url);
  return win;
}

async function start(): Promise<void> {
  if (!app.isPackaged && process.platform === "darwin" && fs.existsSync(DEV_DOCK_ICON)) {
    app.dock?.setIcon(DEV_DOCK_ICON);
  }
  let url: string;
  if (START_URL) {
    url = START_URL;
  } else {
    appServer = await startAppServer({
      webRoot: resolveWebRoot(),
      gatewayUrl: GATEWAY_URL,
      port: PREFERRED_PORT,
    });
    url = appServer.url;
    console.log(`[desktop] serving web build at ${url} (API gateway: ${GATEWAY_URL})`);
  }
  appOrigin = new URL(url).origin;
  createWindow(url);
}

// Ties the taskbar/notifications to the installer's app identity on Windows
if (process.platform === "win32") app.setAppUserModelId("com.otterworks.app");

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    const [win] = BrowserWindow.getAllWindows();
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(() =>
    start().catch((err) => {
      dialog.showErrorBox("OtterWorks failed to start", err.message);
      app.exit(1);
    })
  );

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0 && appOrigin) {
      createWindow(appServer?.url ?? START_URL!);
    }
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  app.on("quit", () => {
    appServer?.close().catch(() => {});
  });
}
