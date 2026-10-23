import { createHmac } from "node:crypto";
import { test, expect, type Page } from "@playwright/test";
import { registerUser, expectDashboard } from "./fixtures/test-helpers";

// QA audit of services/api-gateway through the browser. See docs/qa/api-gateway.md.

const JWT_SECRET =
  process.env.OTTERWORKS_JWT_SECRET ?? "otterworks-local-dev-jwt-secret-change-me-in-production";
const ACCESS_KEY = "otter_access_token";
const REFRESH_KEY = "otter_refresh_token";
const LOGIN_TEXT = "Sign in to your account";

function b64url(input: string | Buffer): string {
  return Buffer.from(input).toString("base64url");
}

function expiredJwt(): string {
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = b64url(
    JSON.stringify({
      sub: "00000000-0000-0000-0000-000000000000",
      email: "qa-expired@otterworks.test",
      type: "access",
      iat: now - 7200,
      exp: now - 3600,
    })
  );
  const sig = createHmac("sha256", JWT_SECRET).update(`${header}.${payload}`).digest("base64url");
  return `${header}.${payload}.${sig}`;
}

async function seedTokens(page: Page, access: string) {
  await page.goto("/login");
  await page.evaluate(
    ([a, r, token]) => {
      localStorage.setItem(a, token);
      localStorage.setItem(r, token);
    },
    [ACCESS_KEY, REFRESH_KEY, access]
  );
}

async function expectBouncedToLogin(page: Page) {
  await expect(page).toHaveURL(/\/login$/, { timeout: 15_000 });
  await expect(page.getByText(LOGIN_TEXT)).toBeVisible();
}

test.describe("QA api-gateway: auth boundary in the browser", () => {
  for (const path of ["/dashboard", "/files", "/documents"]) {
    test(`unauthenticated ${path} redirects to login`, async ({ page }) => {
      const gateway401 = page.waitForResponse(
        (r) => r.url().includes("/api/v1/") && r.status() === 401
      );
      await page.goto(path);
      expect((await gateway401).status()).toBe(401);
      await expectBouncedToLogin(page);
    });
  }

  const badTokens: Array<[string, () => string]> = [
    ["garbage", () => "not-a-jwt"],
    ["expired", expiredJwt],
  ];
  for (const [name, token] of badTokens) {
    test(`${name} token in localStorage is rejected and cleared`, async ({ page }) => {
      await seedTokens(page, token());
      const rejected = page.waitForResponse(
        (r) => r.url().includes("/api/v1/auth/profile") && r.status() === 401
      );
      await page.goto("/files");
      await rejected;
      await expectBouncedToLogin(page);
      const stored = await page.evaluate(
        ([a, r]) => [localStorage.getItem(a), localStorage.getItem(r)],
        [ACCESS_KEY, REFRESH_KEY]
      );
      expect(stored).toEqual([null, null]);
    });
  }
});

test.describe("QA api-gateway: signed-in navigation", () => {
  test("dashboard -> files -> documents all load through the gateway", async ({ page }) => {
    await registerUser(page, { name: "QA Gateway" });
    await expectDashboard(page);

    const gatewayCall = (prefix: string) =>
      page.waitForResponse((r) => r.url().includes(prefix) && r.request().method() === "GET");

    const files = gatewayCall("/api/v1/files");
    await page.goto("/files");
    expect((await files).status()).toBe(200);
    await expect(page.getByRole("heading", { name: /Files|My Files/i })).toBeVisible();

    const docs = gatewayCall("/api/v1/documents");
    await page.goto("/documents");
    expect((await docs).status()).toBe(200);
    await expect(page.getByRole("heading", { name: "Documents", exact: true })).toBeVisible();

    await page.goto("/dashboard");
    await expectDashboard(page);
    await expect(page).not.toHaveURL(/\/login/);
    expect(await page.evaluate((k) => localStorage.getItem(k), ACCESS_KEY)).toBeTruthy();
  });
});
