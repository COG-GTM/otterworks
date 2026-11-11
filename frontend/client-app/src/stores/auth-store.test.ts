import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ authApi: { logout: vi.fn() } }));
vi.mock("react-hot-toast", () => ({ default: { error: vi.fn() } }));

import { authApi } from "@/lib/api";
import { getAccessToken, setAccessToken } from "@/lib/auth-token";
import { useAuthStore } from "./auth-store";

function httpError(status: number): AxiosError {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError("fail", undefined, config, null, {
    status,
    statusText: "",
    headers: {},
    config,
    data: {},
  });
}

describe("logout", () => {
  beforeEach(() => {
    vi.mocked(authApi.logout).mockReset();
    setAccessToken("access");
    useAuthStore.setState({ user: { id: "u1" } as never, isAuthenticated: true });
  });

  it("keeps the session when auth-service could not revoke it", async () => {
    vi.mocked(authApi.logout).mockRejectedValue(httpError(503));
    await useAuthStore.getState().logout();
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    expect(getAccessToken()).toBe("access");
  });

  it("clears the session once revoked, or when none is left (401)", async () => {
    for (const outcome of [Promise.resolve(), Promise.reject(httpError(401))]) {
      vi.mocked(authApi.logout).mockReturnValue(outcome as Promise<void>);
      setAccessToken("access");
      useAuthStore.setState({ isAuthenticated: true });
      await useAuthStore.getState().logout();
      expect(useAuthStore.getState().isAuthenticated).toBe(false);
      expect(getAccessToken()).toBeNull();
    }
  });
});
