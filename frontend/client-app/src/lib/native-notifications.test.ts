import { beforeEach, describe, expect, it, vi } from "vitest";

const platform = vi.hoisted(() => ({ name: "android" }));
const calls = vi.hoisted(() => [] as string[]);

vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: () => platform.name !== "web",
    getPlatform: () => platform.name,
  },
}));

vi.mock("@capacitor/local-notifications", () => ({
  LocalNotifications: {
    checkPermissions: vi.fn(async () => ({ display: "granted" })),
    requestPermissions: vi.fn(async () => ({ display: "granted" })),
    createChannel: vi.fn(async (channel: { id: string }) => {
      calls.push(`createChannel:${channel.id}`);
    }),
    schedule: vi.fn(async (opts: { notifications: { channelId?: string }[] }) => {
      calls.push(`schedule:${opts.notifications[0].channelId ?? "default"}`);
    }),
  },
}));

import { LocalNotifications } from "@capacitor/local-notifications";
import { notifyUploadComplete, notifyUploadFailed } from "./native-notifications";

describe("native upload notifications", () => {
  beforeEach(() => {
    platform.name = "android";
    calls.length = 0;
    vi.clearAllMocks();
  });

  it("creates the upload-errors channel before scheduling a failure on Android", async () => {
    await notifyUploadFailed("q3-report.txt");

    expect(calls).toEqual(["createChannel:upload-errors", "schedule:upload-errors"]);
    expect(LocalNotifications.createChannel).toHaveBeenCalledWith(
      expect.objectContaining({ id: "upload-errors", importance: 4 }),
    );
  });

  it("leaves completion notices on the default channel", async () => {
    await notifyUploadComplete("q3-report.txt");

    expect(calls).toEqual(["schedule:default"]);
  });

  it("skips channel creation on iOS", async () => {
    platform.name = "ios";

    await notifyUploadFailed("q3-report.txt");

    expect(calls).toEqual(["schedule:upload-errors"]);
  });
});
