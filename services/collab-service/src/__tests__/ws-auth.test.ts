import { createServer, type Server } from 'http';
import type { AddressInfo } from 'net';
import { Writable } from 'stream';
import jwt from 'jsonwebtoken';
import pino, { type Logger } from 'pino';
import WebSocket, { WebSocketServer } from 'ws';
import {
  BEARER_SUBPROTOCOL_PREFIX,
  COLLAB_SUBPROTOCOL,
  LOG_REDACT_PATHS,
  authenticateUpgrade,
  createYWebsocketConnectionHandler,
  createYWebsocketUpgradeHandler,
  extractUpgradeToken,
  hasUrlCredential,
  loggablePath,
  selectSubprotocol,
} from '../ws-auth';

const SECRET = 'test-secret';
const token = jwt.sign({ sub: 'user-1' }, SECRET, { expiresIn: '5m' });

describe('extractUpgradeToken', () => {
  it('reads the Authorization bearer header', () => {
    expect(extractUpgradeToken({ headers: { authorization: `Bearer ${token}` } })).toBe(
      token,
    );
  });

  it('reads the bearer subprotocol', () => {
    expect(
      extractUpgradeToken({
        headers: {
          'sec-websocket-protocol': `${COLLAB_SUBPROTOCOL}, ${BEARER_SUBPROTOCOL_PREFIX}${token}`,
        },
      }),
    ).toBe(token);
  });

  it('never reads the URL query string', () => {
    expect(extractUpgradeToken({ url: `/document-1?token=${token}`, headers: {} })).toBe(
      null,
    );
  });
});

describe('authenticateUpgrade', () => {
  it('accepts a valid header token', () => {
    const result = authenticateUpgrade(
      { url: '/document-1', headers: { authorization: `Bearer ${token}` } },
      SECRET,
    );
    expect(result.ok).toBe(true);
  });

  it.each(['token', 'access_token', 'TOKEN', 'jwt'])(
    'rejects a credential in ?%s= even alongside a valid header',
    (param) => {
      expect(
        authenticateUpgrade(
          {
            url: `/document-1?${param}=${token}`,
            headers: { authorization: `Bearer ${token}` },
          },
          SECRET,
        ),
      ).toEqual({ ok: false, reason: 'token_in_url' });
    },
  );

  it('rejects missing and invalid tokens', () => {
    expect(authenticateUpgrade({ url: '/document-1', headers: {} }, SECRET)).toEqual({
      ok: false,
      reason: 'no_token',
    });
    expect(
      authenticateUpgrade(
        { url: '/document-1', headers: { authorization: 'Bearer nope' } },
        SECRET,
      ),
    ).toEqual({ ok: false, reason: 'invalid_token' });
  });
});

describe('helpers', () => {
  it('hasUrlCredential ignores unrelated params', () => {
    expect(hasUrlCredential('/document-1?room=a')).toBe(false);
    expect(hasUrlCredential('/document-1?token=x')).toBe(true);
  });

  it('loggablePath strips the query string', () => {
    expect(loggablePath(`/document-1?token=${token}`)).toBe('/document-1');
  });

  it('selectSubprotocol never echoes the bearer token', () => {
    expect(
      selectSubprotocol(
        new Set([COLLAB_SUBPROTOCOL, `${BEARER_SUBPROTOCOL_PREFIX}${token}`]),
      ),
    ).toBe(COLLAB_SUBPROTOCOL);
    expect(selectSubprotocol(new Set([`${BEARER_SUBPROTOCOL_PREFIX}${token}`]))).toBe(
      false,
    );
  });
});

describe('y-websocket upgrade handler', () => {
  let server: Server;
  let wss: WebSocketServer;
  let baseUrl: string;
  const logLines: string[] = [];
  const logger = {
    warn: (obj: unknown, msg: string) => logLines.push(JSON.stringify({ obj, msg })),
  } as unknown as Logger;

  beforeAll(async () => {
    wss = new WebSocketServer({ noServer: true, handleProtocols: selectSubprotocol });
    wss.on('connection', (ws) => ws.close());
    server = createServer();
    server.on('upgrade', createYWebsocketUpgradeHandler(wss, SECRET, logger));
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    baseUrl = `ws://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  afterAll(async () => {
    wss.close();
    await new Promise((resolve) => server.close(resolve));
  });

  function connect(
    path: string,
    protocols?: string[],
    headers?: Record<string, string>,
  ): Promise<{ status: 'open'; protocol: string } | { status: number }> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`${baseUrl}${path}`, protocols, { headers });
      ws.on('open', () => {
        resolve({ status: 'open', protocol: ws.protocol });
        ws.close();
      });
      ws.on('unexpected-response', (_req, res) =>
        resolve({ status: res.statusCode ?? 0 }),
      );
      ws.on('error', (err) => reject(err));
    });
  }

  it('connects with the bearer subprotocol and negotiates only the app protocol', async () => {
    await expect(
      connect('/document-1', [
        COLLAB_SUBPROTOCOL,
        `${BEARER_SUBPROTOCOL_PREFIX}${token}`,
      ]),
    ).resolves.toEqual({ status: 'open', protocol: COLLAB_SUBPROTOCOL });
  });

  it('connects with an Authorization header', async () => {
    await expect(
      connect('/document-1', undefined, { Authorization: `Bearer ${token}` }),
    ).resolves.toEqual({ status: 'open', protocol: '' });
  });

  it('rejects ?token= with 401 and does not log the token', async () => {
    logLines.length = 0;
    await expect(connect(`/document-1?token=${token}`)).resolves.toEqual({ status: 401 });
    expect(logLines.join('\n')).toContain('token_in_url');
    expect(logLines.join('\n')).toContain('/document-1');
    expect(logLines.join('\n')).not.toContain(token);
  });

  it('rejects a connection without a token', async () => {
    await expect(connect('/document-1')).resolves.toEqual({ status: 401 });
  });
});

describe('logging', () => {
  function capturingLogger(): { logger: Logger; output: () => string } {
    const chunks: string[] = [];
    const stream = new Writable({
      write(chunk, _enc, cb) {
        chunks.push(chunk.toString());
        cb();
      },
    });
    const logger = pino(
      { level: 'info', redact: { paths: LOG_REDACT_PATHS, censor: '[REDACTED]' } },
      stream,
    );
    return { logger, output: () => chunks.join('') };
  }

  it('connection handler logs the path, not the query string', () => {
    const { logger, output } = capturingLogger();
    const setup = jest.fn();
    const req = { url: `/document-42?token=${token}`, headers: {} };
    createYWebsocketConnectionHandler(setup, logger)({} as never, req as never);
    expect(setup).toHaveBeenCalledWith({}, req);
    expect(output()).toContain('"path":"/document-42"');
    expect(output()).toContain('y-websocket_client_connected');
    expect(output()).not.toContain(token);
  });

  it('redacts raw URLs and auth headers passed to the logger', () => {
    const { logger, output } = capturingLogger();
    logger.info(
      {
        url: `/document-1?token=${token}`,
        token,
        req: {
          url: `/document-1?token=${token}`,
          headers: {
            authorization: `Bearer ${token}`,
            'sec-websocket-protocol': `${BEARER_SUBPROTOCOL_PREFIX}${token}`,
          },
        },
      },
      'raw',
    );
    expect(output()).toContain('[REDACTED]');
    expect(output()).not.toContain(token);
  });
});
