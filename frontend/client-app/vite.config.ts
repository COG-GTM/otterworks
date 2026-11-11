/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import pkg from "./package.json" with { type: "json" };

// Dev/preview proxy forwards /api/v1/* to the API gateway (same-origin, no CORS),
// mirroring the old Next.js middleware rewrite. Production uses nginx for the same job.
const apiProxy = {
  "/api/v1": {
    target: process.env.API_GATEWAY_URL || "http://localhost:8080",
    changeOrigin: true,
  },
};
// Allowlist of exact billing routes (anchored so "../" or "%2e%2e" segments
// cannot match): the injected service token never reaches /internal/*.
const billingProxy = {
  "^/billing-api/api/(plans|tenants/[0-9a-fA-F-]{36}/(entitlement|plan-change))(\\?[^/]*)?$": {
    target: process.env.BILLING_SERVICE_URL || "http://localhost:12109",
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/billing-api/, ""),
    headers: process.env.BILLING_SERVICE_TOKEN
      ? { Authorization: `Bearer ${process.env.BILLING_SERVICE_TOKEN}` }
      : undefined,
  },
};

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 3000,
    proxy: { ...apiProxy, ...billingProxy },
  },
  preview: {
    port: 3000,
    proxy: { ...apiProxy, ...billingProxy },
  },
  test: {
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    setupFiles: ["src/test-setup.ts"],
    globals: true,
    environment: "jsdom",
  },
});
