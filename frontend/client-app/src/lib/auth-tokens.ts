import type { AuthTokens } from "@/types";

export const ACCESS_TOKEN_KEY = "otter_access_token";

// Older builds persisted the refresh token here. The SPA never uses it, so it is
// no longer stored and any leftover copy is purged.
export const LEGACY_REFRESH_TOKEN_KEY = "otter_refresh_token";

function hasStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function getAccessToken(): string | null {
  if (!hasStorage()) return null;
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function storeSession(tokens: Pick<AuthTokens, "accessToken">): void {
  if (!hasStorage()) return;
  localStorage.setItem(ACCESS_TOKEN_KEY, tokens.accessToken);
  localStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
}

export function clearSession(): void {
  if (!hasStorage()) return;
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
}

export function purgeLegacyRefreshToken(): void {
  if (!hasStorage()) return;
  localStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
}
