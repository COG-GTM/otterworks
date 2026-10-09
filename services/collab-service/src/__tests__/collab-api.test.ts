import express from 'express';
import type { AddressInfo } from 'net';
import type { Server } from 'http';
import jwt from 'jsonwebtoken';
import { createCollabApiRouter } from '../routes/collab-api';
import type { DocumentAccess, DocumentAccessChecker } from '../services/document-access';
import { HttpDocumentAccessChecker } from '../services/document-access';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';
import { extractBearerToken, isAdmin, verifyAccessToken } from '../middleware/auth';

const JWT_SECRET = 'test-secret-key-for-unit-tests';

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

function token(payload: Record<string, unknown>, secret = JWT_SECRET): string {
  return jwt.sign(payload, secret, { expiresIn: '1h' }); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

const presenceHandler = {
  getDocumentPresence: jest.fn((documentId: string) => ({
    documentId,
    users: [
      {
        userId: 'owner-1',
        email: 'owner@example.com',
        displayName: 'Owner',
        color: '#fff',
        cursor: null,
        selection: null,
        isTyping: false,
        lastActive: 0,
      },
    ],
    count: 1,
  })),
  getActiveDocuments: jest.fn(() => [
    { documentId: 'doc-a', userCount: 1 },
    { documentId: 'doc-b', userCount: 2 },
  ]),
  getActiveDocumentsForUser: jest.fn((userId: string) =>
    userId === 'owner-1' ? [{ documentId: 'doc-a', userCount: 1 }] : [],
  ),
};

describe('collab REST API', () => {
  let server: Server;
  let baseUrl: string;
  let access: DocumentAccess;
  const documentAccess: DocumentAccessChecker = {
    check: jest.fn(async () => access),
  };

  beforeAll(async () => {
    const app = express();
    app.use(
      '/api/v1/collab',
      createCollabApiRouter({
        jwtSecret: JWT_SECRET,
        presenceHandler,
        documentAccess,
        logger: mockLogger,
      }),
    );
    server = app.listen(0, '127.0.0.1');
    await new Promise<void>((resolve) => server.once('listening', () => resolve()));
    baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}/api/v1/collab`;
  });

  afterAll(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  beforeEach(() => {
    jest.clearAllMocks();
    access = 'allowed';
  });

  const get = (path: string, bearer?: string) =>
    fetch(`${baseUrl}${path}`, {
      headers: bearer ? { Authorization: `Bearer ${bearer}` } : {},
    });

  describe('authentication', () => {
    it.each(['/documents', '/documents/doc-a/presence'])(
      'rejects anonymous requests to %s',
      async (path) => {
        const res = await get(path);
        expect(res.status).toBe(401);
        expect(await res.json()).toEqual({ error: 'Authentication required' });
        expect(presenceHandler.getDocumentPresence).not.toHaveBeenCalled();
        expect(presenceHandler.getActiveDocuments).not.toHaveBeenCalled();
      },
    );

    it('rejects tokens signed with another secret', async () => {
      const res = await get('/documents', token({ sub: 'owner-1' }, 'other-secret'));
      expect(res.status).toBe(401);
    });

    it('rejects expired tokens', async () => {
      const expired = jwt.sign(
        { sub: 'owner-1', exp: Math.floor(Date.now() / 1000) - 60 },
        JWT_SECRET,
      ); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
      const res = await get('/documents', expired);
      expect(res.status).toBe(401);
    });

    it('rejects refresh tokens', async () => {
      const res = await get('/documents', token({ sub: 'owner-1', type: 'refresh' }));
      expect(res.status).toBe(401);
    });

    it('rejects tokens without a subject', async () => {
      const res = await get('/documents', token({ email: 'x@example.com' }));
      expect(res.status).toBe(401);
    });
  });

  describe('GET /documents/:id/presence', () => {
    it('returns presence when document-service authorizes the caller', async () => {
      const bearer = token({ sub: 'owner-1' });
      const res = await get('/documents/doc-a/presence', bearer);
      expect(res.status).toBe(200);
      const body = (await res.json()) as { users: Array<{ email: string }> };
      expect(body.users[0].email).toBe('owner@example.com');
      expect(documentAccess.check).toHaveBeenCalledWith('doc-a', `Bearer ${bearer}`);
    });

    it('returns 404 without presence data when the caller is not authorized', async () => {
      access = 'denied';
      const res = await get('/documents/doc-a/presence', token({ sub: 'attacker' }));
      expect(res.status).toBe(404);
      const body = await res.json();
      expect(body).toEqual({ error: 'Document not found' });
      expect(presenceHandler.getDocumentPresence).not.toHaveBeenCalled();
    });

    it('fails closed with 503 when authorization cannot be checked', async () => {
      access = 'unavailable';
      const res = await get('/documents/doc-a/presence', token({ sub: 'owner-1' }));
      expect(res.status).toBe(503);
      expect(presenceHandler.getDocumentPresence).not.toHaveBeenCalled();
    });

    it('lets admins read presence without a document-service check', async () => {
      access = 'denied';
      const res = await get(
        '/documents/doc-a/presence',
        token({ sub: 'admin-1', roles: ['ADMIN'] }),
      );
      expect(res.status).toBe(200);
      expect(documentAccess.check).not.toHaveBeenCalled();
    });
  });

  describe('GET /documents', () => {
    it('lists only the documents a regular user is present in', async () => {
      const res = await get('/documents', token({ sub: 'owner-1', roles: ['USER'] }));
      expect(res.status).toBe(200);
      expect(await res.json()).toEqual({
        documents: [{ documentId: 'doc-a', userCount: 1 }],
        count: 1,
      });
      expect(presenceHandler.getActiveDocuments).not.toHaveBeenCalled();
    });

    it('returns an empty list to users who are in no document', async () => {
      const res = await get('/documents', token({ sub: 'attacker' }));
      expect(await res.json()).toEqual({ documents: [], count: 0 });
    });

    it('lists every active document for admins', async () => {
      const res = await get(
        '/documents',
        token({ sub: 'admin-1', roles: ['ROLE_ADMIN'] }),
      );
      const body = (await res.json()) as { count: number };
      expect(body.count).toBe(2);
    });
  });
});

describe('HttpDocumentAccessChecker', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  const respond = (status: number) => {
    const fetchMock = jest.fn().mockResolvedValue({ status });
    global.fetch = fetchMock as unknown as typeof fetch;
    return fetchMock;
  };

  const checker = new HttpDocumentAccessChecker(
    'http://document-service:8083/',
    1000,
    mockLogger,
  );

  it('forwards the caller token to document-service and allows on 200', async () => {
    const fetchMock = respond(200);
    await expect(checker.check('doc/../x', 'Bearer abc')).resolves.toBe('allowed');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://document-service:8083/api/v1/documents/doc%2F..%2Fx');
    expect(init.headers.Authorization).toBe('Bearer abc');
  });

  it.each([401, 403, 404, 422])('denies on %s', async (status) => {
    respond(status);
    await expect(checker.check('doc-a', 'Bearer abc')).resolves.toBe('denied');
  });

  it.each([302, 500, 503])('reports unavailable on %s', async (status) => {
    respond(status);
    await expect(checker.check('doc-a', 'Bearer abc')).resolves.toBe('unavailable');
  });

  it('reports unavailable when document-service is unreachable', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('ECONNREFUSED')) as never;
    await expect(checker.check('doc-a', 'Bearer abc')).resolves.toBe('unavailable');
  });
});

describe('PresenceHandler.getActiveDocumentsForUser', () => {
  it('returns only documents the user has joined', () => {
    const awareness = new AwarenessService(mockLogger);
    const handler = new PresenceHandler(awareness, mockLogger);
    awareness.addUser('doc-a', 'sock-1', 'user-1', 'One', 'one@example.com');
    awareness.addUser('doc-b', 'sock-2', 'user-2', 'Two', 'two@example.com');
    awareness.addUser('doc-b', 'sock-3', 'user-1', 'One', 'one@example.com');
    awareness.addUser('doc-c', 'sock-4', 'user-3', 'Three', 'three@example.com');

    expect(handler.getActiveDocumentsForUser('user-1')).toEqual([
      { documentId: 'doc-a', userCount: 1 },
      { documentId: 'doc-b', userCount: 2 },
    ]);
    expect(handler.getActiveDocumentsForUser('nobody')).toEqual([]);
  });
});

describe('auth helpers', () => {
  it.each([
    ['Bearer abc', 'abc'],
    ['bearer   abc', 'abc'],
    ['Basic abc', undefined],
    ['Bearer', undefined],
    [undefined, undefined],
  ])('extractBearerToken(%p) -> %p', (header, expected) => {
    expect(extractBearerToken(header)).toBe(expected);
  });

  it('maps verified claims to a user', () => {
    const user = verifyAccessToken(
      token({ sub: 'u1', email: 'u1@example.com', name: 'U One', roles: ['USER'] }),
      JWT_SECRET,
    );
    expect(user).toEqual({
      userId: 'u1',
      email: 'u1@example.com',
      displayName: 'U One',
      roles: ['USER'],
    });
  });

  it.each([
    [['ADMIN'], true],
    [['ROLE_ADMIN'], true],
    [['admin'], true],
    [['USER', 'EDITOR'], false],
    [[], false],
  ])('isAdmin(%p) -> %p', (roles, expected) => {
    expect(isAdmin({ userId: 'u', email: '', displayName: '', roles })).toBe(expected);
  });
});
