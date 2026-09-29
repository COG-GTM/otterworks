import { beforeEach, describe, expect, it, vi } from "vitest";

const platform = vi.hoisted(() => ({ name: "android" }));
const plugin = vi.hoisted(() => ({
  checkPermissions: vi.fn(),
  requestPermissions: vi.fn(),
  createChannel: vi.fn(),
  schedule: vi.fn(),
}));

vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: () => platform.name !== "web",
    getPlatform: () => platform.name,
  },
}));
vi.mock("@capacitor/local-notifications", () => ({ LocalNotifications: plugin }));

async function load() {
  vi.resetModules();
  return import("./native-notifications");
}

describe("native upload notifications", () => {
  beforeEach(() => {
    platform.name = "android";
    vi.clearAllMocks();
    plugin.checkPermissions.mockResolvedValue({ display: "granted" });
    plugin.createChannel.mockResolvedValue(undefined);
    plugin.schedule.mockResolvedValue({ notifications: [] });
  });

  it("creates the upload-errors channel on Android before posting a failure to it", async () => {
    const { notifyUploadFailed } = await load();

    await notifyUploadFailed("report.pdf");

    expect(plugin.createChannel).toHaveBeenCalledWith(
      expect.objectContaining({ id: "upload-errors", name: "Upload errors" }),
    );
    expect(plugin.createChannel.mock.invocationCallOrder[0]).toBeLessThan(
      plugin.schedule.mock.invocationCallOrder[0],
    );
    expect(plugin.schedule).toHaveBeenCalledWith({
      notifications: [
        expect.objectContaining({ title: "Upload failed", channelId: "upload-errors" }),
      ],
    });
  });

  it("creates the channel only once across failures", async () => {
    const { notifyUploadFailed } = await load();

    await notifyUploadFailed("a.txt");
    await notifyUploadFailed("b.txt");

    expect(plugin.createChannel).toHaveBeenCalledTimes(1);
    expect(plugin.schedule).toHaveBeenCalledTimes(2);
  });

  it("retries channel creation after a failed attempt", async () => {
    const { notifyUploadFailed } = await load();
    plugin.createChannel.mockRejectedValueOnce(new Error("boom"));

    await notifyUploadFailed("a.txt");
    await notifyUploadFailed("b.txt");

    expect(plugin.createChannel).toHaveBeenCalledTimes(2);
    expect(plugin.schedule).toHaveBeenCalledTimes(1);
  });

  it("posts completions to the default channel without creating one", async () => {
    const { notifyUploadComplete } = await load();

    await notifyUploadComplete("report.pdf");

    expect(plugin.createChannel).not.toHaveBeenCalled();
    expect(plugin.schedule).toHaveBeenCalledWith({
      notifications: [
        expect.objectContaining({ title: "Upload complete", channelId: undefined }),
      ],
    });
  });

  it("skips channel creation on iOS, which has no channels", async () => {
    platform.name = "ios";
    const { notifyUploadFailed } = await load();

    await notifyUploadFailed("report.pdf");

    expect(plugin.createChannel).not.toHaveBeenCalled();
    expect(plugin.schedule).toHaveBeenCalledTimes(1);
  });

  it("does nothing on web", async () => {
    platform.name = "web";
    const { notifyUploadFailed } = await load();

    await notifyUploadFailed("report.pdf");

    expect(plugin.checkPermissions).not.toHaveBeenCalled();
    expect(plugin.schedule).not.toHaveBeenCalled();
  });
});
