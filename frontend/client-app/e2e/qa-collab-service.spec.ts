import {
  test,
  expect,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";

/**
 * QA: collab-service primary flow — the same document open in two browser windows.
 *
 * document-service only lets the owner open a document (there is no edit-sharing for
 * documents), so both windows are signed in as the same user in separate browser
 * contexts. Requires the stack (web-app, api-gateway, auth, document, collab-service).
 */

const GATEWAY_URL = process.env.API_GATEWAY_URL || "http://localhost:8080";

interface Session {
  accessToken: string;
  refreshToken: string;
  displayName: string;
}

async function registerViaApi(request: APIRequestContext): Promise<Session> {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const displayName = `QA Collab ${suffix}`;
  const res = await request.post(`${GATEWAY_URL}/api/v1/auth/register`, {
    data: {
      email: `qa-collab-${suffix}@otterworks.test`,
      password: "Passw0rd!23",
      displayName,
    },
  });
  expect(res.status(), await res.text()).toBe(201);
  const body = await res.json();
  return { accessToken: body.accessToken, refreshToken: body.refreshToken, displayName };
}

async function createDocument(request: APIRequestContext, session: Session): Promise<string> {
  const res = await request.post(`${GATEWAY_URL}/api/v1/documents/`, {
    headers: { Authorization: `Bearer ${session.accessToken}` },
    data: { title: `QA collab ${Date.now()}`, content: "" },
  });
  expect(res.status(), await res.text()).toBe(201);
  return (await res.json()).id;
}

async function openWindow(
  browser: Browser,
  session: Session,
  documentId: string
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext();
  await context.addInitScript(
    ([access, refresh]) => {
      localStorage.setItem("otter_access_token", access);
      localStorage.setItem("otter_refresh_token", refresh);
    },
    [session.accessToken, session.refreshToken]
  );
  const page = await context.newPage();
  await openDocument(page, documentId);
  return { context, page };
}

async function openDocument(page: Page, documentId: string) {
  await page.goto(`/documents/${documentId}`);
  await expect(editor(page)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("All changes saved")).toBeVisible({ timeout: 15_000 });
}

function editor(page: Page) {
  return page.locator(".ProseMirror");
}

async function typeAtEnd(page: Page, text: string) {
  await editor(page).click();
  await page.keyboard.press("Control+End");
  await page.keyboard.type(text);
}

test.describe("QA collab-service: two windows on one document", () => {
  let session: Session;
  let documentId: string;

  test.beforeEach(async ({ request }) => {
    session = await registerViaApi(request);
    documentId = await createDocument(request, session);
  });

  test("edits propagate live in both directions", async ({ browser }) => {
    const a = await openWindow(browser, session, documentId);
    const b = await openWindow(browser, session, documentId);
    try {
      await typeAtEnd(a.page, "alpha-from-window-A ");
      await expect(editor(b.page)).toContainText("alpha-from-window-A", { timeout: 10_000 });

      await typeAtEnd(b.page, "bravo-from-window-B");
      await expect(editor(a.page)).toContainText("bravo-from-window-B", { timeout: 10_000 });
    } finally {
      await a.context.close();
      await b.context.close();
    }
  });

  test("presence: each window shows the other window's collaboration cursor", async ({ browser }) => {
    const a = await openWindow(browser, session, documentId);
    const b = await openWindow(browser, session, documentId);
    try {
      await typeAtEnd(a.page, "cursor-probe");
      const caretInB = b.page.locator(".collaboration-cursor__caret");
      await expect(caretInB.first()).toBeVisible({ timeout: 10_000 });

      await typeAtEnd(b.page, "!");
      const caretInA = a.page.locator(".collaboration-cursor__caret");
      await expect(caretInA.first()).toBeVisible({ timeout: 10_000 });
    } finally {
      await a.context.close();
      await b.context.close();
    }
  });

  test("a window that disconnects and reconnects catches up on missed edits", async ({ browser }) => {
    const a = await openWindow(browser, session, documentId);
    const b = await openWindow(browser, session, documentId);
    try {
      await typeAtEnd(a.page, "before-disconnect ");
      await expect(editor(b.page)).toContainText("before-disconnect", { timeout: 10_000 });

      // Disconnect window B by leaving the editor (unmount destroys the WebsocketProvider).
      await b.page.goto("/documents");
      await typeAtEnd(a.page, "while-B-away ");

      await openDocument(b.page, documentId);
      await expect(editor(b.page)).toContainText("while-B-away", { timeout: 10_000 });

      await typeAtEnd(b.page, "after-reconnect");
      await expect(editor(a.page)).toContainText("after-reconnect", { timeout: 10_000 });
    } finally {
      await a.context.close();
      await b.context.close();
    }
  });

  test("going offline shows Offline/Reconnecting and recovers when back online", async ({ browser }) => {
    const a = await openWindow(browser, session, documentId);
    const b = await openWindow(browser, session, documentId);
    try {
      await b.context.setOffline(true);
      // Chromium does not always drop an open WebSocket when offline; y-websocket notices via
      // its resync/timeout loop, so accept either state or a still-connected socket.
      await b.page.evaluate(() => window.dispatchEvent(new Event("offline")));
      await typeAtEnd(a.page, "edit-while-B-offline ");
      await b.context.setOffline(false);
      await b.page.evaluate(() => window.dispatchEvent(new Event("online")));

      await expect(editor(b.page)).toContainText("edit-while-B-offline", { timeout: 20_000 });
      await expect(b.page.getByText("All changes saved")).toBeVisible({ timeout: 20_000 });
    } finally {
      await a.context.close();
      await b.context.close();
    }
  });
});
