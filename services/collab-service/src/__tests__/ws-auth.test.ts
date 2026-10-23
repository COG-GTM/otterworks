import { createServer, Server } from 'http';
import type { AddressInfo } from 'net';
import { Writable } from 'stream';
import jwt from 'jsonwebtoken';
import pino from 'pino';
import WebSocket, { WebSocketServer } from 'ws';
import {
  BEARER_SUBPROTOCOL_PREFIX,
  COLLAB_SUBPROTOCOL,
  LOG_REDACT_PATHS,
  authenticateUpgrade,
  createYWebsocketUpgradeHandler,
  extractUpgradeToken,
  loggablePath,
  selectSubprotocol,
  verifyAccessToken,
} from '../ws-auth';

const SECRET = 'test-secret-key-for-unit-tests';

function sign(payload: Record<string, unknown>, secret = SECRET): string {
  return jwt.sign(payload, secret, { expiresIn: '1h' }); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

const accessToken = () => sign({ sub: 'user-1', type: 'access', email: 'a@b.c' });
const refreshToken = () => sign({ sub: 'user-1', type: 'refresh', jti: 'r-1' });

describe('verifyAccessToken', () => {
  it('accepts an access token', () => {
    expect(verifyAccessToken(accessToken(), SECRET).sub).toBe('user-1');
  });

  it('rejects a refresh token', () => {
    expect(() => verifyAccessToken(refreshToken(), SECRET)).toThrow(
      'not an access token',
    );
  });

  it('rejects a token without a type claim', () => {
    expect(() => verifyAccessToken(sign({ sub: 'user-1' }), SECRET)).toThrow();
  });

  it('rejects a token without a subject', () => {
    expect(() => verifyAccessToken(sign({ type: 'access' }), SECRET)).toThrow();
  });

  it('rejects a token signed with another secret', () => {
    expect(() =>
      verifyAccessToken(sign({ sub: 'u', type: 'access' }, 'other-secret'), SECRET),
    ).toThrow();
  });

  it('rejects an unsigned token', () => {
    const unsigned = jwt.sign({ sub: 'u', type: 'access' }, '', { algorithm: 'none' });
    expect(() => verifyAccessToken(unsigned, SECRET)).toThrow();
  });
});

describe('extractUpgradeToken', () => {
  it('reads the bearer subprotocol', () => {
    const headers = {
      'sec-websocket-protocol': `${COLLAB_SUBPROTOCOL}, ${BEARER_SUBPROTOCOL_PREFIX}a.b.c`,
    };
    expect(extractUpgradeToken({ headers })).toBe('a.b.c');
  });

  it('reads the Authorization header', () => {
    expect(extractUpgradeToken({ headers: { authorization: 'Bearer a.b.c' } })).toBe(
      'a.b.c',
    );
  });

  it('never reads the URL', () => {
    expect(extractUpgradeToken({ url: '/doc?token=a.b.c', headers: {} })).toBeNull();
  });
});

describe('authenticateUpgrade', () => {
  const bearer = (token: string) => ({
    'sec-websocket-protocol': `${COLLAB_SUBPROTOCOL}, ${BEARER_SUBPROTOCOL_PREFIX}${token}`,
  });

  it('accepts an access token in the subprotocol header', () => {
    const result = authenticateUpgrade(
      { url: '/document-1', headers: bearer(accessToken()) },
      SECRET,
    );
    expect(result).toMatchObject({ ok: true, claims: { sub: 'user-1' } });
  });

  it('rejects a token in the URL even when a header token is valid', () => {
    const result = authenticateUpgrade(
      { url: `/document-1?token=${accessToken()}`, headers: bearer(accessToken()) },
      SECRET,
    );
    expect(result).toEqual({ ok: false, reason: 'token_in_url' });
  });

  it('rejects a refresh token', () => {
    const result = authenticateUpgrade(
      { url: '/document-1', headers: bearer(refreshToken()) },
      SECRET,
    );
    expect(result).toEqual({ ok: false, reason: 'invalid_token' });
  });

  it('rejects a request without a token', () => {
    expect(authenticateUpgrade({ url: '/document-1', headers: {} }, SECRET)).toEqual({
      ok: false,
      reason: 'no_token',
    });
  });
});

describe('selectSubprotocol / loggablePath', () => {
  it('echoes only the app protocol', () => {
    const offered = new Set([COLLAB_SUBPROTOCOL, `${BEARER_SUBPROTOCOL_PREFIX}a.b.c`]);
    expect(selectSubprotocol(offered)).toBe(COLLAB_SUBPROTOCOL);
    expect(selectSubprotocol(new Set([`${BEARER_SUBPROTOCOL_PREFIX}a.b.c`]))).toBe(false);
  });

  it('strips the query string', () => {
    expect(loggablePath('/document-1?token=a.b.c')).toBe('/document-1');
    expect(loggablePath(undefined)).toBe('/');
  });
});

describe('y-websocket upgrade handler', () => {
  let server: Server;
  let wss: WebSocketServer;
  let lines: string[];
  let port: number;

  beforeEach((done) => {
    lines = [];
    const sink = new Writable({
      write(chunk, _enc, cb) {
        lines.push(chunk.toString());
        cb();
      },
    });
    const logger = pino(
      { redact: { paths: LOG_REDACT_PATHS, censor: '[REDACTED]' } },
      sink,
    );
    wss = new WebSocketServer({ noServer: true, handleProtocols: selectSubprotocol });
    wss.on('connection', (conn, req) => {
      logger.info({ path: loggablePath(req.url) }, 'y-websocket_client_connected');
      conn.close();
    });
    server = createServer();
    server.on('upgrade', createYWebsocketUpgradeHandler(wss, SECRET, logger));
    server.listen(0, '127.0.0.1', () => {
      port = (server.address() as AddressInfo).port;
      done();
    });
  });

  afterEach((done) => {
    wss.close();
    server.close(() => done());
  });

  function connect(path: string, protocols: string[] = []) {
    return new Promise<{ protocol?: string; error?: string }>((resolve) => {
      const ws = new WebSocket(`ws://127.0.0.1:${port}${path}`, protocols);
      ws.on('open', () => {
        resolve({ protocol: ws.protocol });
        ws.close();
      });
      ws.on('error', (err) => resolve({ error: err.message }));
    });
  }

  it('connects the owner with a subprotocol token and keeps it out of logs', async () => {
    const token = accessToken();
    const result = await connect('/document-1', [
      COLLAB_SUBPROTOCOL,
      `${BEARER_SUBPROTOCOL_PREFIX}${token}`,
    ]);
    expect(result).toEqual({ protocol: COLLAB_SUBPROTOCOL });
    const log = lines.join('');
    expect(log).toContain('"path":"/document-1"');
    expect(log).not.toContain(token);
  });

  it('rejects a query-string token with 401 and does not log it', async () => {
    const token = accessToken();
    const result = await connect(`/document-1?token=${token}`);
    expect(result.error).toContain('401');
    const log = lines.join('');
    expect(log).toContain('token_in_url');
    expect(log).not.toContain(token);
  });

  it('rejects a refresh token with 401', async () => {
    const result = await connect('/document-1', [
      COLLAB_SUBPROTOCOL,
      `${BEARER_SUBPROTOCOL_PREFIX}${refreshToken()}`,
    ]);
    expect(result.error).toContain('401');
  });
});

describe('LOG_REDACT_PATHS', () => {
  it('censors a raw url field', () => {
    const out: string[] = [];
    const sink = new Writable({
      write(chunk, _enc, cb) {
        out.push(chunk.toString());
        cb();
      },
    });
    pino({ redact: { paths: LOG_REDACT_PATHS, censor: '[REDACTED]' } }, sink).info(
      { url: '/document-1?token=secret.jwt.value' },
      'x',
    );
    expect(out.join('')).not.toContain('secret.jwt.value');
  });
});
