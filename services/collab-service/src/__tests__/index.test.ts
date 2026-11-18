import http from 'http';
import { EventEmitter } from 'events';
import type { AddressInfo } from 'net';
import jwt from 'jsonwebtoken';
import WebSocket from 'ws';
import { io as clientIO } from 'socket.io-client';

const JWT_SECRET = 'index-test-secret';

const mockRedisState = { connectFails: false, pong: 'PONG' };

jest.mock('ioredis', () => ({
  __esModule: true,
  default: jest.fn().mockImplementation(() => {
    const emitter = new EventEmitter();
    return Object.assign(emitter, {
      connect: jest.fn(() =>
        mockRedisState.connectFails
          ? Promise.reject(new Error('ECONNREFUSED'))
          : Promise.resolve(),
      ),
      disconnect: jest.fn(),
      ping: jest.fn(() => Promise.resolve(mockRedisState.pong)),
      getBuffer: jest.fn().mockResolvedValue(null),
      setex: jest.fn().mockResolvedValue('OK'),
      set: jest.fn().mockResolvedValue('OK'),
      hset: jest.fn().mockResolvedValue(1),
      hgetall: jest.fn().mockResolvedValue({}),
      hincrby: jest.fn().mockResolvedValue(1),
      expire: jest.fn().mockResolvedValue(1),
      del: jest.fn().mockResolvedValue(1),
      lpush: jest.fn().mockResolvedValue(1),
      ltrim: jest.fn().mockResolvedValue('OK'),
      lrange: jest.fn().mockResolvedValue([]),
    });
  }),
}));

function sign(payload: Record<string, unknown>, secret = JWT_SECRET): string {
  return jwt.sign(payload, secret, { expiresIn: '1h' }); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

let ywsDocs: Map<string, { destroy(): void }> = new Map();

interface Booted {
  promClient: typeof import('prom-client');
  server: http.Server;
  base: string;
  port: number;
  exit: jest.SpyInstance;
}

async function boot(opts: { connectFails?: boolean } = {}): Promise<Booted> {
  mockRedisState.connectFails = !!opts.connectFails;
  mockRedisState.pong = 'PONG';
  process.env.HTTP_PORT = '0';
  process.env.JWT_SECRET = JWT_SECRET;
  process.env.NODE_ENV = 'production';
  process.env.LOG_LEVEL = 'silent';

  let server!: http.Server;
  const realCreate = http.createServer;
  const createSpy = jest.spyOn(http, 'createServer').mockImplementation(((
    ...args: Parameters<typeof http.createServer>
  ) => {
    server = realCreate(...args);
    return server;
  }) as typeof http.createServer);
  const exit = jest.spyOn(process, 'exit').mockImplementation((() => undefined) as never);

  let promClient!: typeof import('prom-client');
  delete (globalThis as Record<string, unknown>)['__ $YJS$ __'];
  jest.isolateModules(() => {
    /* eslint-disable @typescript-eslint/no-var-requires */
    promClient = require('prom-client');
    ywsDocs = require('y-websocket/bin/utils').docs;
    require('../index');
    /* eslint-enable @typescript-eslint/no-var-requires */
  });
  createSpy.mockRestore();

  await new Promise<void>((resolve) => {
    if (server.listening) resolve();
    else server.once('listening', () => resolve());
  });
  const port = (server.address() as AddressInfo).port;
  return { promClient, server, port, base: `http://127.0.0.1:${port}`, exit };
}

async function shutdown(
  b: Booted,
  signal: 'SIGTERM' | 'SIGINT' = 'SIGTERM',
): Promise<() => void> {
  const realSetTimeout = global.setTimeout;
  const forced: Array<{ handle: NodeJS.Timeout; fn: () => void }> = [];
  const spy = jest.spyOn(global, 'setTimeout').mockImplementation(((
    fn: () => void,
    ms?: number,
  ) => {
    const handle = realSetTimeout(fn, ms);
    if (ms === 10000) forced.push({ handle, fn });
    return handle;
  }) as typeof setTimeout);
  const closed = new Promise((resolve) => b.server.once('close', resolve));
  process.emit(signal);
  await closed;
  await new Promise((resolve) => setImmediate(resolve));
  spy.mockRestore();
  forced.forEach(({ handle }) => clearTimeout(handle));
  return () => forced.forEach(({ fn }) => fn());
}

function wsStatus(
  url: string,
  headers: Record<string, string> = {},
): Promise<number | 'open'> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url, { headers });
    ws.on('open', () => {
      ws.close();
      resolve('open');
    });
    ws.on('unexpected-response', (_req, res) => resolve(res.statusCode ?? 0));
    ws.on('error', (err) => reject(err));
  });
}

describe('index (service entrypoint)', () => {
  const originalEnv = { ...process.env };
  let booted: Booted | null = null;

  afterEach(async () => {
    if (booted) {
      await shutdown(booted);
      booted.exit.mockRestore();
      booted = null;
    }
    ywsDocs.forEach((doc) => doc.destroy());
    ywsDocs.clear();
    process.removeAllListeners('SIGTERM');
    process.removeAllListeners('SIGINT');
    process.env = { ...originalEnv };
    jest.useRealTimers();
  });

  it('serves health, metrics, presence and document listing', async () => {
    booted = await boot();

    const health = await fetch(`${booted.base}/health`);
    expect(health.status).toBe(200);
    expect(await health.json()).toMatchObject({
      status: 'healthy',
      service: 'collab-service',
      redis: 'connected',
      activeDocuments: 0,
    });

    const metricsRes = await fetch(`${booted.base}/metrics`);
    expect(metricsRes.status).toBe(200);
    expect(metricsRes.headers.get('content-type')).toMatch(/^text\/plain/);
    expect(await metricsRes.text()).toContain('collab_active_connections');

    const presence = await fetch(`${booted.base}/api/v1/collab/documents/d1/presence`);
    expect(await presence.json()).toEqual({ documentId: 'd1', users: [], count: 0 });

    const docs = await fetch(`${booted.base}/api/v1/collab/documents`);
    expect(await docs.json()).toEqual({ documents: [], count: 0 });
  });

  it('reports degraded health when Redis does not answer PONG', async () => {
    booted = await boot();
    mockRedisState.pong = 'NOPE';
    const res = await fetch(`${booted.base}/health`);
    expect(res.status).toBe(503);
    expect(await res.json()).toMatchObject({ status: 'degraded', redis: 'disconnected' });
  });

  it('still starts when Redis is unreachable', async () => {
    booted = await boot({ connectFails: true });
    const res = await fetch(`${booted.base}/api/v1/collab/documents`);
    expect(res.status).toBe(200);
  });

  it('lists documents with live presence after a Socket.IO join', async () => {
    booted = await boot();
    const client = clientIO(booted.base, {
      auth: { token: sign({ sub: 'u1', name: 'Una' }) },
      transports: ['websocket'],
    });
    await new Promise<void>((resolve, reject) => {
      client.on('connect', () => resolve());
      client.on('connect_error', reject);
    });
    await new Promise((resolve) =>
      client.emit('join-document', { documentId: 'd1' }, resolve),
    );

    const docs = (await (
      await fetch(`${booted.base}/api/v1/collab/documents`)
    ).json()) as unknown;
    expect(docs).toEqual({ documents: [{ documentId: 'd1', userCount: 1 }], count: 1 });
    const presence = (await (
      await fetch(`${booted.base}/api/v1/collab/documents/d1/presence`)
    ).json()) as { users: unknown[] };
    expect(presence.users[0]).toMatchObject({ userId: 'u1', displayName: 'Una' });
    const health = (await (await fetch(`${booted.base}/health`)).json()) as {
      activeDocuments: number;
    };
    expect(health.activeDocuments).toBe(1);

    client.disconnect();
  });

  describe('y-websocket upgrade auth', () => {
    // engine.io closes unhandled non-Socket.IO upgrades on a 1s timer
    afterAll(() => new Promise((resolve) => setTimeout(resolve, 1100)));

    it('rejects upgrades without a token', async () => {
      booted = await boot();
      expect(await wsStatus(`ws://127.0.0.1:${booted.port}/doc-1`)).toBe(401);
    });

    it('rejects upgrades with an invalid token', async () => {
      booted = await boot();
      const token = sign({ sub: 'u1' }, 'wrong-secret');
      expect(await wsStatus(`ws://127.0.0.1:${booted.port}/doc-1?token=${token}`)).toBe(
        401,
      );
    });

    it('accepts a valid token in the query string', async () => {
      booted = await boot();
      const token = sign({ sub: 'u1' });
      expect(await wsStatus(`ws://127.0.0.1:${booted.port}/doc-1?token=${token}`)).toBe(
        'open',
      );
    });

    it('accepts a valid bearer token header', async () => {
      booted = await boot();
      expect(
        await wsStatus(`ws://127.0.0.1:${booted.port}/doc-2`, {
          Authorization: `Bearer ${sign({ sub: 'u1' })}`,
        }),
      ).toBe('open');
    });
  });

  it('returns 500 when metrics collection fails', async () => {
    booted = await boot();
    jest
      .spyOn(booted.promClient.Registry.prototype, 'metrics')
      .mockRejectedValueOnce(new Error('collect failed'));
    const res = await fetch(`${booted.base}/metrics`);
    expect(res.status).toBe(500);
    expect(await res.text()).toBe('Error collecting metrics');
  });

  it('shuts down gracefully on SIGINT and exits 0', async () => {
    const b = await boot();
    const fireForceExit = await shutdown(b, 'SIGINT');
    expect(b.exit).toHaveBeenCalledWith(0);
    expect(b.exit).not.toHaveBeenCalledWith(1);

    fireForceExit();
    expect(b.exit).toHaveBeenCalledWith(1);
    b.exit.mockRestore();
  });
});
