import { useEffect, type ReactNode } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { authApi } from "@/lib/api";
import { refreshAccessToken } from "@/lib/api-client";
import { getAccessToken, purgeLegacyTokenStorage } from "@/lib/auth-session";

export function AuthProvider({ children }: { children: ReactNode }) {
  const { setUser, setLoading } = useAuthStore();

  useEffect(() => {
    purgeLegacyTokenStorage();
    setLoading(true);
    const restore = getAccessToken() ? Promise.resolve(getAccessToken()) : refreshAccessToken();
    restore
      .then((token) => (token ? authApi.getProfile() : null))
      .then((user) => setUser(user))
      .catch(() => setUser(null));
  }, [setUser, setLoading]);

  return <>{children}</>;
}
