import axios, { type InternalAxiosRequestConfig } from "axios";
import { Capacitor } from "@capacitor/core";
import { getAccessToken, setAccessToken } from "./auth-token";

// ── snake_case → camelCase helpers ────────────────────────────
function snakeToCamel(s: string): string {
  return s.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}

function transformKeys(obj: unknown): unknown {
  if (Array.isArray(obj)) return obj.map(transformKeys);
  if (obj !== null && typeof obj === "object" && !(obj instanceof Date)) {
    return Object.fromEntries(
      Object.entries(obj as Record<string, unknown>).map(([k, v]) => [
        snakeToCamel(k),
        transformKeys(v),
      ])
    );
  }
  return obj;
}

// Web builds call the same-origin /api/v1 proxy (Vite dev server locally, nginx in
// production) to avoid CORS issues; the proxy forwards /api/v1/* to the API gateway
// (configured via API_GATEWAY_URL env var). Native (Capacitor) builds have no
// same-origin server, so they call the API gateway directly — the default targets
// the Android emulator's host-loopback alias, which is plain HTTP by design in
// local dev. Any real deployment must point VITE_API_BASE_URL at an https
// gateway; the scheme below is only the local-dev default.
const NATIVE_API_SCHEME = "http";
const NATIVE_API_BASE_URL = `${NATIVE_API_SCHEME}://10.0.2.2:8080/api/v1`;

export const API_BASE_URL = Capacitor.isNativePlatform()
  ? import.meta.env.VITE_API_BASE_URL || NATIVE_API_BASE_URL
  : "/api/v1";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let refreshInFlight: Promise<string | null> | null = null;

// Exchanges the HttpOnly refresh cookie for a new in-memory access token. Uses bare
// axios so no (possibly stale) Authorization header is attached; concurrent callers
// share one request because auth-service rotates the refresh token on every use.
export function refreshAccessToken(): Promise<string | null> {
  if (!refreshInFlight) {
    refreshInFlight = axios
      .post<{ accessToken?: string }>(`${API_BASE_URL}/auth/refresh`, null, {
        withCredentials: true,
      })
      .then(({ data }) => {
        const token = data?.accessToken ?? null;
        setAccessToken(token);
        return token;
      })
      .catch(() => {
        setAccessToken(null);
        return null;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

const NO_REFRESH_PATHS = ["/auth/login", "/auth/register", "/auth/refresh"];

type RetriableConfig = InternalAxiosRequestConfig & { _authRetried?: boolean };

apiClient.interceptors.response.use(
  (response) => {
    if (response.data) {
      response.data = transformKeys(response.data);
    }
    return response;
  },
  async (error) => {
    const config = error.config as RetriableConfig | undefined;
    if (error.response?.status === 401 && config && typeof window !== "undefined") {
      const url = config.url || "";
      if (!config._authRetried && !NO_REFRESH_PATHS.some((p) => url.includes(p))) {
        config._authRetried = true;
        const token = await refreshAccessToken();
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
          return apiClient(config);
        }
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);
