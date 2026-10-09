import { EventEmitter } from 'events';
import { createServer, type Server } from 'http';
import type { AddressInfo } from 'net';
import WebSocket, { WebSocketServer } from 'ws';
import * as Y from 'yjs';
import * as encoding from 'lib0/encoding';
import * as syncProtocol from 'y-protocols/sync';
import {
  CLOSE_MESSAGE_TOO_BIG,
  CLOSE_POLICY_VIOLATION,
  CLOSE_TRY_AGAIN_LATER,
  YWebsocketGuard,
  docNameFromUrl,
  isDocUpdateMessage,
  type SharedDocLike,
  type YWebsocketLimits,
} from '../services/ywebsocket-guard';

// eslint-disable-next-line @typescript-eslint/no-var-requires
const yUtils = require('y-websocket/bin/utils');

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
  fatal: jest.fn(),
  trace: jest.fn(),
  child: jest.fn().mockReturnThis(),
  level: 'info',
} as never;

const LIMITS: YWebsocketLimits = {
  maxPayloadBytes: 1024,
  maxDocBytes: 2048,
  maxDocs: 3,
  maxDocNameLength: 64,
  maxConnectionsPerUser: 4,
  maxRoomsPerUser: 2,
  rateWindowMs: 1000,
  maxMessagesPerWindow: 5,
  maxBytesPerWindow: 4096,
};

class FakeDoc extends EventEmitter implements SharedDocLike {
  conns = new Map<unknown, unknown>();
  destroy = jest.fn();
}

class FakeConn extends EventEmitter {
  readonly OPEN = 1;
  readyState = 1;
  close = jest.fn(() => {
    this.readyState = 2;
    this.emit('close');
  });
}

function updateMessage(payloadBytes: number): Buffer {
  return Buffer.concat([Buffer.from([0, 2]), Buffer.alloc(payloadBytes, 1)]);
}

function awarenessMessage(payloadBytes: number): Buffer {
  return Buffer.concat([Buffer.from([1]), Buffer.alloc(payloadBytes, 1)]);
}

describe('YWebsocketGuard', () => {
  let docs: Map<string, FakeDoc>;
  let clock: number;
  let guard: YWebsocketGuard;

  const connect = (userId: string, docName: string) => {
    const conn = new FakeConn();
    const onMessage = jest.fn();
    const accepted = guard.attach(conn as unknown as WebSocket, userId, docName, () => {
      conn.on('message', onMessage);
      const doc = docs.get(docName) ?? new FakeDoc();
      doc.conns.set(conn, new Set());
      conn.once('close', () => doc.conns.delete(conn));
      docs.set(docName, doc);
    });
    return { conn, onMessage, accepted };
  };

  beforeEach(() => {
    docs = new Map();
    clock = 0;
    guard = new YWebsocketGuard(
      LIMITS,
      docs,
      () => 0,
      mockLogger,
      () => clock,
    );
  });

  it('derives the doc name like y-websocket', () => {
    expect(docNameFromUrl('/document-abc?token=x')).toBe('document-abc');
    expect(docNameFromUrl(undefined)).toBe('');
  });

  it('identifies sync step2 and update messages', () => {
    expect(isDocUpdateMessage(Buffer.from([0, 0, 1]))).toBe(false);
    expect(isDocUpdateMessage(Buffer.from([0, 1, 1]))).toBe(true);
    expect(isDocUpdateMessage(Buffer.from([0, 2, 1]))).toBe(true);
    expect(isDocUpdateMessage(Buffer.from([1, 2, 1]))).toBe(false);
    expect(isDocUpdateMessage(Buffer.alloc(0))).toBe(false);
  });

  it('rejects invalid or oversized document names', () => {
    expect(guard.admit('u1', '')).toMatchObject({ ok: false, status: 400 });
    expect(guard.admit('u1', 'a'.repeat(65))).toMatchObject({ ok: false, status: 400 });
    expect(guard.admit('u1', 'doc/../x')).toMatchObject({ ok: false, status: 400 });
    expect(guard.admit('u1', 'document-1')).toEqual({ ok: true });
  });

  it('caps the number of rooms per user and frees them on close', () => {
    const a = connect('u1', 'doc-a');
    connect('u1', 'doc-b');
    expect(guard.admit('u1', 'doc-c')).toMatchObject({ ok: false, status: 429 });
    expect(guard.admit('u1', 'doc-a')).toEqual({ ok: true });
    expect(guard.admit('u2', 'doc-c')).toEqual({ ok: true });

    const refused = connect('u1', 'doc-c');
    expect(refused.accepted).toBe(false);
    expect(refused.conn.close).toHaveBeenCalledWith(
      CLOSE_POLICY_VIOLATION,
      'too many documents',
    );

    a.conn.close();
    expect(guard.admit('u1', 'doc-c')).toEqual({ ok: true });
  });

  it('caps connections per user', () => {
    for (let i = 0; i < LIMITS.maxConnectionsPerUser; i++) {
      expect(connect('u1', 'doc-a').accepted).toBe(true);
    }
    expect(guard.admit('u1', 'doc-a')).toMatchObject({ ok: false, status: 429 });
  });

  it('evicts idle documents at capacity and refuses when none are idle', () => {
    const a = connect('u1', 'doc-a');
    connect('u2', 'doc-b');
    connect('u3', 'doc-c');
    expect(guard.admit('u4', 'doc-d')).toMatchObject({ ok: false, status: 503 });
    const refused = connect('u4', 'doc-d');
    expect(refused.conn.close).toHaveBeenCalledWith(
      CLOSE_TRY_AGAIN_LATER,
      'document capacity reached',
    );

    const docA = docs.get('doc-a')!;
    a.conn.close();
    expect(connect('u4', 'doc-d').accepted).toBe(true);
    expect(docs.has('doc-a')).toBe(false);
    expect(docA.destroy).toHaveBeenCalled();
    expect(docs.size).toBe(LIMITS.maxDocs);
  });

  it('closes connections that exceed the message rate', () => {
    const { conn, onMessage } = connect('u1', 'doc-a');
    for (let i = 0; i < LIMITS.maxMessagesPerWindow; i++) {
      conn.emit('message', awarenessMessage(1), true);
    }
    expect(onMessage).toHaveBeenCalledTimes(LIMITS.maxMessagesPerWindow);
    conn.emit('message', awarenessMessage(1), true);
    expect(onMessage).toHaveBeenCalledTimes(LIMITS.maxMessagesPerWindow);
    expect(conn.close).toHaveBeenCalledWith(
      CLOSE_POLICY_VIOLATION,
      'rate limit exceeded',
    );
  });

  it('resets the rate window over time', () => {
    const { conn, onMessage } = connect('u1', 'doc-a');
    for (let i = 0; i < LIMITS.maxMessagesPerWindow * 3; i++) {
      conn.emit('message', awarenessMessage(1), true);
      clock += LIMITS.rateWindowMs / LIMITS.maxMessagesPerWindow;
    }
    expect(onMessage).toHaveBeenCalledTimes(LIMITS.maxMessagesPerWindow * 3);
    expect(conn.close).not.toHaveBeenCalled();
  });

  it('closes connections that exceed the byte rate', () => {
    const { conn, onMessage } = connect('u1', 'doc-a');
    for (let i = 0; i < 5; i++) {
      conn.emit('message', awarenessMessage(1000), true);
    }
    expect(onMessage).toHaveBeenCalledTimes(4);
    expect(conn.close).toHaveBeenCalledWith(
      CLOSE_POLICY_VIOLATION,
      'rate limit exceeded',
    );
  });

  it('drops document updates past the per-document size cap', () => {
    const { conn, onMessage } = connect('u1', 'doc-a');
    const doc = docs.get('doc-a')!;
    doc.emit('update', new Uint8Array(1500));

    conn.emit('message', awarenessMessage(900), true);
    expect(onMessage).toHaveBeenCalledTimes(1);

    conn.emit('message', updateMessage(600), true);
    expect(onMessage).toHaveBeenCalledTimes(1);
    expect(conn.close).toHaveBeenCalledWith(
      CLOSE_MESSAGE_TOO_BIG,
      'document size limit exceeded',
    );
  });

  it('ignores messages after the connection started closing', () => {
    const { conn, onMessage } = connect('u1', 'doc-a');
    conn.readyState = 2;
    conn.emit('message', awarenessMessage(1), true);
    expect(onMessage).not.toHaveBeenCalled();
  });
});

describe('y-websocket server limits (integration)', () => {
  let server: Server;
  let wss: WebSocketServer;
  let url: string;

  beforeAll(async () => {
    const guard = new YWebsocketGuard(
      LIMITS,
      yUtils.docs,
      (doc) => Y.encodeStateAsUpdate(doc as unknown as Y.Doc).byteLength,
      mockLogger,
    );
    server = createServer();
    wss = new WebSocketServer({ noServer: true, maxPayload: LIMITS.maxPayloadBytes });
    wss.on('connection', (conn, req) => {
      const docName = docNameFromUrl(req.url);
      guard.attach(conn, 'user-1', docName, () =>
        yUtils.setupWSConnection(conn, req, { docName }),
      );
    });
    server.on('upgrade', (req, socket, head) => {
      wss.handleUpgrade(req, socket, head, (ws) => wss.emit('connection', ws, req));
    });
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    url = `ws://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  afterAll(async () => {
    wss.clients.forEach((c) => c.terminate());
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  const open = (docName: string) =>
    new Promise<WebSocket>((resolve, reject) => {
      const ws = new WebSocket(`${url}/${docName}`);
      ws.once('open', () => resolve(ws));
      ws.once('error', reject);
    });

  const closed = (ws: WebSocket) =>
    new Promise<number>((resolve) => ws.once('close', (code) => resolve(code)));

  const yUpdate = (text: string): Buffer => {
    const doc = new Y.Doc();
    doc.getText('t').insert(0, text);
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, 0);
    syncProtocol.writeUpdate(encoder, Y.encodeStateAsUpdate(doc));
    return Buffer.from(encoding.toUint8Array(encoder));
  };

  it('closes the socket with 1009 when a frame exceeds maxPayload', async () => {
    const ws = await open('doc-payload');
    const done = closed(ws);
    ws.send(Buffer.alloc(LIMITS.maxPayloadBytes + 1));
    expect(await done).toBe(CLOSE_MESSAGE_TOO_BIG);
  });

  it('applies small updates and refuses updates that overflow the doc cap', async () => {
    const ws = await open('doc-size');
    ws.send(yUpdate('hello'));
    await new Promise((r) => setTimeout(r, 50));
    expect(yUtils.docs.get('doc-size').getText('t').toString()).toBe('hello');

    const done = closed(ws);
    for (let i = 0; i < 3; i++) {
      ws.send(yUpdate('x'.repeat(900)));
    }
    expect(await done).toBe(CLOSE_MESSAGE_TOO_BIG);
    const length = yUtils.docs.get('doc-size').getText('t').length;
    expect(length).toBeLessThan(5 + 3 * 900);
  });
});
