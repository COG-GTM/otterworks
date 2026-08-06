import { isAxiosError } from "axios";
import { apiClient } from "./api-client";

// Reports a failed file upload to the gateway's incident relay, which opens a
// Devin triage session server-side (the Devin API key never reaches the
// browser). Fire-and-forget: reporting failures must never affect the upload
// UI, so all errors are swallowed.
export async function reportUploadFailure(fileName: string, err: unknown): Promise<void> {
  const httpStatus = isAxiosError(err) ? (err.response?.status ?? null) : null;
  const message = err instanceof Error ? err.message : String(err);
  try {
    await apiClient.post("/incidents/upload-failure", {
      file_name: fileName,
      http_status: httpStatus,
      message,
    });
  } catch {
    // Best-effort only.
  }
}
