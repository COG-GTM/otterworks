import { Capacitor } from "@capacitor/core";
import { LocalNotifications } from "@capacitor/local-notifications";

let notificationId = 0;

// Failures are routed to their own channel so users can keep upload errors
// audible while muting routine completion notices.
const UPLOAD_ERROR_CHANNEL_ID = "upload-errors";

async function hasDisplayPermission(): Promise<boolean> {
  const { display } = await LocalNotifications.checkPermissions();
  if (display === "granted") return true;
  if (display === "denied") return false;
  const requested = await LocalNotifications.requestPermissions();
  return requested.display === "granted";
}

// No-ops on web, where the surrounding UI already reports upload status.
async function notify(title: string, body: string, channelId?: string): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  try {
    if (!(await hasDisplayPermission())) return;
    await LocalNotifications.schedule({
      notifications: [{ id: ++notificationId, title, body, channelId }],
    });
  } catch {
    // A missed notification must never surface as an upload error.
  }
}

export function notifyUploadComplete(fileName: string): Promise<void> {
  return notify("Upload complete", `${fileName} finished uploading.`);
}

export function notifyUploadFailed(fileName: string): Promise<void> {
  return notify(
    "Upload failed",
    `${fileName} could not be uploaded.`,
    UPLOAD_ERROR_CHANNEL_ID,
  );
}
