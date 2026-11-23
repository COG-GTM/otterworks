import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.otterworks.app",
  appName: "OtterWorks",
  webDir: "dist",
  backgroundColor: "#f4f5f7",
  android: {
    path: "mobile/android",
    // WebView-level gate: lets the https-scheme webview issue requests to
    // plain-http origins. On its own this is NOT sufficient — Android's
    // platform-level cleartext policy also applies. Release builds keep
    // cleartext disabled (AndroidManifest.xml usesCleartextTraffic=false), so
    // http still fails there; debug builds allow cleartext to 10.0.2.2 only,
    // via mobile/android/app/src/debug/res/xml/network_security_config.xml,
    // which is what makes the local dev gateway reachable. Point
    // VITE_API_BASE_URL at an https gateway for production builds.
    allowMixedContent: true,
  },
  ios: {
    path: "mobile/ios",
  },
  plugins: {
    SplashScreen: {
      launchAutoHide: false,
      backgroundColor: "#FDBB6F",
    },
  },
};

export default config;
