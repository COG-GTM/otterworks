import type { AuthTokens } from "@/types";

const ACCESS_TOKEN_KEY = "otter_access_token";
// Older builds persisted the 30-day refresh token here; it is never read by the
// client, so it is no longer stored and any leftover copy is purged.
const LEGACY_REFRESH_TOKEN_KEY = "otter_refresh_token";

export function storeSession(tokens: Pick<AuthTokens, "accessToken">): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, tokens.accessToken);
  localStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
}

export function purgeLegacyRefreshToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
}
