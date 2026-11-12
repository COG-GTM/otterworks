import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse, delay } from "msw";
import { AxiosError, type AxiosAdapter } from "axios";
import { billingServer } from "../test-setup";
import { apiClient } from "./api-client";

const TOKEN = "access-token";

function rejectWith(status: number): { adapter: AxiosAdapter; original: () => AxiosError } {
  let original: AxiosError | undefined;
  const adapter: AxiosAdapter = async (config) => {
    original = new AxiosError("failed", undefined, config, undefined, {
      status,
      statusText: "",
      headers: {},
      config,
      data: {},
    });
    throw original;
  };
  return {
    adapter,
    original: () => {
      if (!original) throw new Error("adapter was not called");
      return original;
    },
  };
}

async function captureRejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("expected request to reject");
}

describe("apiClient response interceptor", () => {
  beforeEach(() => {
    localStorage.setItem("otter_access_token", TOKEN);
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("rejects non-401 errors with the original AxiosError", async () => {
    billingServer.use(
      http.get("/api/v1/files", () => HttpResponse.json({ error: "boom" }, { status: 500 }))
    );

    const error = await captureRejection(apiClient.get("/files"));

    expect(error).toBeInstanceOf(AxiosError);
    expect((error as AxiosError).response?.status).toBe(500);
    expect((error as AxiosError).config?.url).toBe("/files");
  });

  it("rejects a 401 with the original error after the token verifies, keeping the session", async () => {
    billingServer.use(
      http.get("/api/v1/files", () => HttpResponse.json({}, { status: 401 })),
      http.get("/api/v1/auth/profile", () => HttpResponse.json({ id: "u1" }))
    );

    const error = await captureRejection(apiClient.get("/files"));

    expect(error).toBeInstanceOf(AxiosError);
    expect((error as AxiosError).response?.status).toBe(401);
    expect((error as AxiosError).config?.url).toBe("/files");
    expect(localStorage.getItem("otter_access_token")).toBe(TOKEN);
  });

  it("rejects a concurrent 401 with its own error while a verification is in flight", async () => {
    let profileCalls = 0;
    billingServer.use(
      http.get("/api/v1/files", () => HttpResponse.json({}, { status: 401 })),
      http.get("/api/v1/documents", async () => {
        await delay(20);
        return HttpResponse.json({}, { status: 401 });
      }),
      http.get("/api/v1/auth/profile", async () => {
        profileCalls += 1;
        await delay(100);
        return HttpResponse.json({ id: "u1" });
      })
    );

    const [first, second] = await Promise.all([
      captureRejection(apiClient.get("/files")),
      captureRejection(apiClient.get("/documents")),
    ]);

    expect((first as AxiosError).config?.url).toBe("/files");
    expect((second as AxiosError).config?.url).toBe("/documents");
    expect((second as AxiosError).response?.status).toBe(401);
    expect(profileCalls).toBe(1);
  });

  it("rejects /auth/ 401s without verifying the token", async () => {
    let profileCalls = 0;
    billingServer.use(
      http.post("/api/v1/auth/login", () => HttpResponse.json({}, { status: 401 })),
      http.get("/api/v1/auth/profile", () => {
        profileCalls += 1;
        return HttpResponse.json({ id: "u1" });
      })
    );

    const error = await captureRejection(apiClient.post("/auth/login", {}));

    expect((error as AxiosError).response?.status).toBe(401);
    expect(profileCalls).toBe(0);
  });

  it.each([500, 401])("rejects a %i with the exact error object the request produced", async (status) => {
    billingServer.use(http.get("/api/v1/auth/profile", () => HttpResponse.json({ id: "u1" })));
    const { adapter, original } = rejectWith(status);

    const error = await captureRejection(apiClient.get("/files", { adapter }));

    expect(error).toBe(original());
  });
});
