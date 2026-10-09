import { createServer, type Server } from 'http';
import type { AddressInfo } from 'net';
import { Writable } from 'stream';
import pino from 'pino';
import WebSocket, { WebSocketServer } from 'ws';
import {
  BEARER_SUBPROTOCOL_PREFIX,
  COLLAB_SUBPROTOCOL,
  LOG_REDACT_PATHS,
  extractUpgradeToken,
  loggablePath,
  parseSubprotocols,
  selectSubprotocol,
} from '../ws-auth';

const JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEifQ.c2lnbmF0dXJl';

describe('parseSubprotocols', () => {
  it('splits and trims comma-separated values', () => {
    expect(parseSubprotocols(' a , b,,c ')).toEqual(['a', 'b', 'c']);
    expect(parseSubprotocols(['a, b', 'c'])).toEqual(['a', 'b', 'c']);
    expect(parseSubprotocols(undefined)).toEqual([]);
  });
});

describe('extractUpgradeToken', () => {
  it('reads the bearer subprotocol', () => {
    const token = extractUpgradeToken({
      url: '/document-1',
      headers: {
        'sec-websocket-protocol': `${COLLAB_SUBPROTOCOL}, ${BEARER_SUBPROTOCOL_PREFIX}${JWT}`,
      },
    });
    expect(token).toBe(JWT);
  });

  it('prefers the subprotocol over the Authorization header and query string', () => {
    const token = extractUpgradeToken({
      url: '/document-1?token=from-query',
      headers: {
        authorization: 'Bearer from-header',
        'sec-websocket-protocol': `${BEARER_SUBPROTOCOL_PREFIX}${JWT}`,
      },
    });
    expect(token).toBe(JWT);
  });

  it('falls back to the Authorization header, then the legacy query parameter', () => {
    expect(
      extractUpgradeToken({ url: '/d?token=q', headers: { authorization: 'Bearer h' } }),
    ).toBe('h');
    expect(extractUpgradeToken({ url: '/d?token=q', headers: {} })).toBe('q');
  });

  it('returns null when no token is supplied', () => {
    expect(extractUpgradeToken({ url: '/document-1', headers: {} })).toBeNull();
    expect(
      extractUpgradeToken({
        url: '/document-1?token=',
        headers: {
          'sec-websocket-protocol': `${COLLAB_SUBPROTOCOL}, ${BEARER_SUBPROTOCOL_PREFIX}`,
        },
      }),
    ).toBeNull();
  });
});

describe('selectSubprotocol', () => {
  it('echoes the app protocol and never the bearer token', () => {
    expect(
      selectSubprotocol(
        new Set([`${BEARER_SUBPROTOCOL_PREFIX}${JWT}`, COLLAB_SUBPROTOCOL]),
      ),
    ).toBe(COLLAB_SUBPROTOCOL);
    expect(selectSubprotocol(new Set([`${BEARER_SUBPROTOCOL_PREFIX}${JWT}`]))).toBe(
      false,
    );
  });
});

describe('loggablePath', () => {
  it('drops the query string', () => {
    expect(loggablePath(`/document-42?token=${JWT}`)).toBe('/document-42');
    expect(loggablePath('/document-42')).toBe('/document-42');
    expect(loggablePath(undefined)).toBe('/');
  });
});

describe('log redaction', () => {
  function capture() {
    const lines: string[] = [];
    const stream = new Writable({
      write(chunk, _enc, cb) {
        lines.push(chunk.toString());
        cb();
      },
    });
    const logger = pino(
      { redact: { paths: LOG_REDACT_PATHS, censor: '[REDACTED]' } },
      stream,
    );
    return { logger, lines };
  }

  it('censors URLs, tokens and auth headers that reach the logger', () => {
    const { logger, lines } = capture();
    logger.info({ url: `/document-1?token=${JWT}` }, 'a');
    logger.info({ token: JWT }, 'b');
    logger.info(
      {
        req: {
          url: `/d?token=${JWT}`,
          headers: {
            authorization: `Bearer ${JWT}`,
            'sec-websocket-protocol': `${BEARER_SUBPROTOCOL_PREFIX}${JWT}`,
          },
        },
      },
      'c',
    );
    expect(lines).toHaveLength(3);
    for (const line of lines) {
      expect(line).not.toContain(JWT);
      expect(line).toContain('[REDACTED]');
    }
  });
});

describe('y-websocket upgrade over a real server', () => {
  let server: Server;
  let port: number;
  const logged: string[] = [];

  beforeAll((done) => {
    const stream = new Writable({
      write(chunk, _enc, cb) {
        logged.push(chunk.toString());
        cb();
      },
    });
    const logger = pino(
      { redact: { paths: LOG_REDACT_PATHS, censor: '[REDACTED]' } },
      stream,
    );
    const wss = new WebSocketServer({
      noServer: true,
      handleProtocols: selectSubprotocol,
    });
    wss.on('connection', (conn, req) => {
      logger.info({ path: loggablePath(req.url) }, 'y-websocket_client_connected');
      conn.close();
    });
    server = createServer();
    server.on('upgrade', (request, socket, head) => {
      if (extractUpgradeToken(request) !== JWT) {
        socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n');
        socket.destroy();
        return;
      }
      wss.handleUpgrade(request, socket, head, (ws) =>
        wss.emit('connection', ws, request),
      );
    });
    server.listen(0, '127.0.0.1', () => {
      port = (server.address() as AddressInfo).port;
      done();
    });
  });

  afterAll((done) => {
    server.close(() => done());
  });

  function connect(path: string, protocols?: string[]): Promise<string> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`ws://127.0.0.1:${port}${path}`, protocols);
      ws.on('open', () => resolve(ws.protocol));
      ws.on('error', reject);
    });
  }

  it('accepts the bearer subprotocol and negotiates only the app protocol', async () => {
    const negotiated = await connect('/document-7', [
      COLLAB_SUBPROTOCOL,
      `${BEARER_SUBPROTOCOL_PREFIX}${JWT}`,
    ]);
    expect(negotiated).toBe(COLLAB_SUBPROTOCOL);
  });

  it('still accepts the legacy ?token= query parameter', async () => {
    await expect(connect(`/document-7?token=${JWT}`)).resolves.toBe('');
  });

  it('rejects connections without a valid token', async () => {
    await expect(connect('/document-7', [COLLAB_SUBPROTOCOL])).rejects.toThrow(/401/);
  });

  it('never writes the token to the connection log', () => {
    const connected = logged.filter((line) =>
      line.includes('y-websocket_client_connected'),
    );
    expect(connected).toHaveLength(2);
    for (const line of connected) {
      expect(line).toContain('"path":"/document-7"');
      expect(line).not.toContain(JWT);
    }
  });
});
