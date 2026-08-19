import { describe, expect, it, vi, beforeEach } from "vitest";

const get = vi.fn();
vi.mock("./api-client", () => ({
  apiClient: { get, post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  API_BASE_URL: "/api/v1",
}));

const { incidentsApi } = await import("./api");

describe("incidentsApi.findForUpload", () => {
  beforeEach(() => get.mockReset());

  it("matches the incident opened for the failed file", async () => {
    get.mockResolvedValue({
      data: {
        incidents: [
          { id: "2", title: "File upload failed: other.txt" },
          { id: "1", title: "File upload failed: report.pdf", devinSessionUrl: "https://app.devin.ai/sessions/abc" },
        ],
      },
    });

    const incident = await incidentsApi.findForUpload("report.pdf");

    expect(incident?.devinSessionUrl).toBe("https://app.devin.ai/sessions/abc");
  });

  it("returns null when no incident mentions the file", async () => {
    get.mockResolvedValue({ data: { incidents: [{ id: "2", title: "File upload failed: other.txt" }] } });

    await expect(incidentsApi.findForUpload("report.pdf")).resolves.toBeNull();
  });
});
