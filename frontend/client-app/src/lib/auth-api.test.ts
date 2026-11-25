import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("./api-client", () => ({
  apiClient: {
    get: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
}));

import { apiClient } from "./api-client";
import { authApi } from "./api";

const client = vi.mocked(apiClient);

// DV-4: auth-service maps only GET and PUT on /profile.
describe("authApi.updateProfile", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("saves the profile with PUT /auth/profile", async () => {
    const updates = { displayName: "Ada Lovelace" };
    const saved = { id: "u-1", email: "ada@example.com", displayName: "Ada Lovelace" };
    client.put.mockResolvedValue({ data: saved });

    const result = await authApi.updateProfile(updates);

    expect(client.put).toHaveBeenCalledWith("/auth/profile", updates);
    expect(client.patch).not.toHaveBeenCalled();
    expect(result).toEqual(saved);
  });
});
