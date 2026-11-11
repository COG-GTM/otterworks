import { useEffect, type ReactNode } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { authApi } from "@/lib/api";
import { refreshAccessToken } from "@/lib/api-client";
import { clearLegacyTokenStorage, getAccessToken } from "@/lib/auth-token";

export function AuthProvider({ children }: { children: ReactNode }) {
  const { setUser, setLoading } = useAuthStore();

  useEffect(() => {
    clearLegacyTokenStorage();
    let cancelled = false;

    setLoading(true);
    (async () => {
      const token = getAccessToken() ?? (await refreshAccessToken());
      if (!token) return null;
      return authApi.getProfile();
    })()
      .then((user) => !cancelled && setUser(user))
      .catch(() => !cancelled && setUser(null));

    return () => {
      cancelled = true;
    };
  }, [setUser, setLoading]);

  return <>{children}</>;
}
