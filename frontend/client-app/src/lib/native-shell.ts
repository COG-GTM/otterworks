import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
import { SplashScreen } from "@capacitor/splash-screen";

// Wires native shell behaviour; no-ops on web.
export function initNativeShell(): void {
  if (!Capacitor.isNativePlatform()) return;

  // Keep the splash up until React has painted, so there is no blank WebView flash.
  requestAnimationFrame(() => {
    void SplashScreen.hide();
  });

  void App.addListener("backButton", ({ canGoBack }) => {
    if (canGoBack) {
      window.history.back();
    } else {
      void App.minimizeApp();
    }
  });
}
