import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { setupServer } from "msw/node";

export const billingServer = setupServer();

beforeAll(() => billingServer.listen({ onUnhandledRequest: "error" }));
afterEach(() => billingServer.resetHandlers());
afterAll(() => billingServer.close());
