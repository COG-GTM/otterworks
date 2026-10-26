import { createServer, type Server } from 'http';
import type { AddressInfo } from 'net';
import jwt from 'jsonwebtoken';
import WebSocket from 'ws';
import type { Logger } from 'pino';
import { attachYjsWebsocket, YJS_ACCESS_REVOKED } from '../handlers/yjs-websocket';
import type { DocumentAccessChecker } from '../services/document-access';

const SECRET = 'test-secret-for-yjs-websocket-handler';
const ALICE = '11111111-1111-4111-8111-111111111111';
const MALLORY = '22222222-2222-4222-8222-222222222222';
const ALICE_DOC = '3f2b8c1e-7d4a-4c9b-9a1e-5b6c7d8e9f01';
const logger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
} as unknown as Logger;

const accessToken = (sub: string, extra: Record<string, unknown> = {}) =>
  jwt.sign({ sub, type: 'access', ...extra }, SECRET, { expiresIn: '5m' });

type Outcome = { opened: true; ws: WebSocket } | { opened: false; status: number };

describe('attachYjsWebsocket', () => {
  let server: Server;
  let port: number;
  let canAccess: jest.Mock;
  let setupWSConnection: jest.Mock;

  function start(revalidateIntervalMs = 0): Promise<void> {
    server = createServer();
    attachYjsWebsocket(server, {
      jwtSecret: SECRET,
      documentAccess: { canAccess } as DocumentAccessChecker,
      setupWSConnection,
      logger,
      revalidateIntervalMs,
    });
    return new Promise((resolve) =>
      server.listen(0, '127.0.0.1', () => {
        port = (server.address() as AddressInfo).port;
        resolve();
      }),
    );
  }

  function connect(path: string, headers: Record<string, string> = {}): Promise<Outcome> {
    return new Promise((resolve) => {
      const ws = new WebSocket(`ws://127.0.0.1:${port}${path}`, { headers });
      ws.on('open', () => resolve({ opened: true, ws }));
      ws.on('unexpected-response', (_req, res) =>
        resolve({ opened: false, status: res.statusCode ?? 0 }),
      );
      ws.on('error', () => resolve({ opened: false, status: 0 }));
    });
  }

  beforeEach(() => {
    // document-service grants Alice her own document and nothing else
    canAccess = jest.fn(
      async (_token: string, userId: string, documentId: string) =>
        userId === ALICE && documentId === ALICE_DOC,
    );
    setupWSConnection = jest.fn();
  });

  afterEach(async () => {
    await new Promise((resolve) => server.close(resolve));
  });

  it('refuses another user opening a document they cannot access (403, no sync)', async () => {
    await start();
    const result = await connect(`/document-${ALICE_DOC}?token=${accessToken(MALLORY)}`);
    expect(result).toEqual({ opened: false, status: 403 });
    expect(canAccess).toHaveBeenCalledWith(expect.any(String), MALLORY, ALICE_DOC);
    expect(setupWSConnection).not.toHaveBeenCalled();
  });

  it('also refuses the bearer-header form for a non-owner', async () => {
    await start();
    const result = await connect(`/document-${ALICE_DOC}`, {
      Authorization: `Bearer ${accessToken(MALLORY)}`,
    });
    expect(result).toEqual({ opened: false, status: 403 });
    expect(setupWSConnection).not.toHaveBeenCalled();
  });

  it('lets the owner join, binding the room to the authorized document id', async () => {
    await start();
    const result = await connect(`/document-${ALICE_DOC}?token=${accessToken(ALICE)}`);
    expect(result.opened).toBe(true);
    if (result.opened) result.ws.close();
    expect(setupWSConnection).toHaveBeenCalledTimes(1);
    expect(setupWSConnection.mock.calls[0][2]).toEqual({
      docName: `document-${ALICE_DOC}`,
    });
  });

  it('rejects missing, forged and refresh tokens with 401', async () => {
    await start();
    expect(await connect(`/document-${ALICE_DOC}`)).toEqual({
      opened: false,
      status: 401,
    });
    const forged = jwt.sign({ sub: ALICE, type: 'access' }, 'wrong-secret');
    expect(await connect(`/document-${ALICE_DOC}?token=${forged}`)).toEqual({
      opened: false,
      status: 401,
    });
    const refresh = accessToken(ALICE, { type: 'refresh' });
    expect(await connect(`/document-${ALICE_DOC}?token=${refresh}`)).toEqual({
      opened: false,
      status: 401,
    });
    expect(canAccess).not.toHaveBeenCalled();
    expect(setupWSConnection).not.toHaveBeenCalled();
  });

  it('rejects room names that are not document-<uuid> with 400', async () => {
    await start();
    const token = accessToken(ALICE);
    for (const path of [
      `/anything?token=${token}`,
      `/document-${ALICE_DOC.toUpperCase()}?token=${token}`,
      `/document-${ALICE_DOC}/extra?token=${token}`,
    ]) {
      expect(await connect(path)).toEqual({ opened: false, status: 400 });
    }
    expect(setupWSConnection).not.toHaveBeenCalled();
  });

  it('fails closed with 503 when the access check errors', async () => {
    canAccess.mockRejectedValue(new Error('document-service down'));
    await start();
    const result = await connect(`/document-${ALICE_DOC}?token=${accessToken(ALICE)}`);
    expect(result).toEqual({ opened: false, status: 503 });
    expect(setupWSConnection).not.toHaveBeenCalled();
  });

  it('closes an open connection once access is revoked', async () => {
    await start(20);
    const result = await connect(`/document-${ALICE_DOC}?token=${accessToken(ALICE)}`);
    expect(result.opened).toBe(true);
    if (!result.opened) return;
    const closed = new Promise<number>((resolve) =>
      result.ws.on('close', (code) => resolve(code)),
    );
    canAccess.mockResolvedValue(false);
    expect(await closed).toBe(YJS_ACCESS_REVOKED);
    expect(canAccess).toHaveBeenLastCalledWith(expect.any(String), ALICE, ALICE_DOC, {
      fresh: true,
    });
  });

  it('leaves Socket.IO upgrades alone', async () => {
    await start();
    // stands in for Socket.IO's own upgrade listener
    const upgrade = jest.fn((_req, socket: { destroy: () => void }) => socket.destroy());
    server.on('upgrade', upgrade);
    const ws = new WebSocket(
      `ws://127.0.0.1:${port}/socket.io/?EIO=4&transport=websocket`,
    );
    ws.on('error', () => undefined);
    await new Promise((resolve) => setTimeout(resolve, 50));
    ws.terminate();
    expect(upgrade).toHaveBeenCalled();
    expect(canAccess).not.toHaveBeenCalled();
    expect(setupWSConnection).not.toHaveBeenCalled();
  });
});
