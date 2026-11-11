// The access token lives only in module memory so it is never persisted where other
// same-origin scripts can harvest it. The refresh token is an HttpOnly cookie set by
// auth-service, so page JavaScript never sees it at all.
let accessToken: string | null = null;

// Keys older builds persisted tokens under; removed on startup so upgraded browsers
// do not keep long-lived credentials in localStorage.
const LEGACY_TOKEN_STORAGE_KEYS = ["otter_access_token", "otter_refresh_token"];

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function clearLegacyTokenStorage(): void {
  if (typeof window === "undefined") return;
  try {
    for (const key of LEGACY_TOKEN_STORAGE_KEYS) {
      window.localStorage.removeItem(key);
    }
  } catch {
    // Storage may be unavailable (privacy mode); nothing to clean up.
  }
}
