// The access token lives only in memory; the refresh token is an HttpOnly cookie
// set by the auth-service, so neither is readable from Web Storage.
const LEGACY_STORAGE_KEYS = ["otter_access_token", "otter_refresh_token"];

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token || null;
}

export function clearSession(): void {
  accessToken = null;
  purgeLegacyTokenStorage();
}

export function purgeLegacyTokenStorage(): void {
  if (typeof window === "undefined") return;
  for (const key of LEGACY_STORAGE_KEYS) {
    window.localStorage.removeItem(key);
  }
}
