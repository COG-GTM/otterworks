import { describe, it, expect, beforeEach, vi } from "vitest";
import type { AxiosAdapter, AxiosError } from "axios";
import axios from "axios";
import { apiClient } from "./api-client";

function rejectWith(status: number): AxiosAdapter {
  return (config) =>
    Promise.reject(
      new axios.AxiosError(
        `HTTP ${status}`,
        String(status),
        config,
        null,
        { status, statusText: "", headers: {}, config, data: {} },
      ),
    );
}

describe("apiClient response error interceptor", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("rejects with the original error for non-401 responses", async () => {
    const err = await apiClient
      .get("/documents", { adapter: rejectWith(500) })
      .catch((e: AxiosError) => e);
    expect(axios.isAxiosError(err)).toBe(true);
    expect((err as AxiosError).response?.status).toBe(500);
  });

  it("rejects with the original error for 401 on /auth/ routes without re-verifying", async () => {
    const verify = vi.spyOn(axios, "get");
    const err = await apiClient
      .post("/auth/login", {}, { adapter: rejectWith(401) })
      .catch((e: AxiosError) => e);
    expect((err as AxiosError).response?.status).toBe(401);
    expect(verify).not.toHaveBeenCalled();
  });

  it("rejects with the original error after verifying the token on a 401", async () => {
    localStorage.setItem("otter_access_token", "tok");
    const verify = vi.spyOn(axios, "get").mockResolvedValue({ status: 200 });
    const err = await apiClient
      .get("/documents", { adapter: rejectWith(401) })
      .catch((e: AxiosError) => e);
    expect((err as AxiosError).response?.status).toBe(401);
    expect((err as AxiosError).config?.url).toBe("/documents");
    expect(verify).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem("otter_access_token")).toBe("tok");
  });

  it("rejects concurrent 401s with their own errors while a verification is in flight", async () => {
    let release!: () => void;
    const verify = vi
      .spyOn(axios, "get")
      .mockReturnValue(new Promise((resolve) => { release = () => resolve({ status: 200 }); }));
    const first = apiClient.get("/documents", { adapter: rejectWith(401) }).catch((e: AxiosError) => e);
    await vi.waitFor(() => expect(verify).toHaveBeenCalledTimes(1));
    const second = await apiClient
      .get("/files", { adapter: rejectWith(401) })
      .catch((e: AxiosError) => e);
    expect((second as AxiosError).config?.url).toBe("/files");
    release();
    expect(((await first) as AxiosError).config?.url).toBe("/documents");
    expect(verify).toHaveBeenCalledTimes(1);
  });
});
