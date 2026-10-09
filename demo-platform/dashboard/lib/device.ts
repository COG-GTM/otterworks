import crypto from "node:crypto";

// "Trusted device" cookie for the login limiter (see lib/ratelimit.ts). Issued
// only after a correct passcode; a browser that presents a valid one gets its
// own rate-limit bucket and is exempt from global pressure, so anonymous
// traffic cannot lock out facilitators who have signed in from it before.
// It grants no access by itself — the session cookie is still required.

export const DEVICE_COOKIE = "ow_ops_device";
export const DEVICE_TTL_SECONDS = 90 * 24 * 60 * 60;

const DEVICE_ID_RE = /^[A-Za-z0-9_-]{22}$/;

// Domain-separated from session-token signatures so neither token can be
// replayed as the other.
function sign(secret: string, body: string): string {
  return crypto.createHmac("sha256", secret).update(`device.${body}`).digest("base64url");
}

export function newDeviceId(): string {
  return crypto.randomBytes(16).toString("base64url");
}

/** Token: `<deviceId>.<expEpochSeconds>.<hmac>`. */
export function signDeviceToken(
  deviceId: string,
  secret: string,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): string {
  const body = `${deviceId}.${nowSeconds + DEVICE_TTL_SECONDS}`;
  return `${body}.${sign(secret, body)}`;
}

/** Returns the device id for a valid, unexpired token; otherwise null. */
export function verifyDeviceToken(
  token: string | undefined,
  secret: string,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): string | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [deviceId, expRaw, sig] = parts as [string, string, string];
  if (!DEVICE_ID_RE.test(deviceId) || !/^\d{1,12}$/.test(expRaw)) return null;
  const expected = Buffer.from(sign(secret, `${deviceId}.${expRaw}`));
  const given = Buffer.from(sig);
  if (given.length !== expected.length || !crypto.timingSafeEqual(given, expected)) return null;
  if (Number(expRaw) < nowSeconds) return null;
  return deviceId;
}

export function deviceCookie(token: string) {
  return {
    name: DEVICE_COOKIE,
    value: token,
    httpOnly: true as const,
    secure: true as const,
    sameSite: "strict" as const,
    path: "/api/auth/login",
    maxAge: DEVICE_TTL_SECONDS,
  };
}
