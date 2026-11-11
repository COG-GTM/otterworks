import express from 'express';
import { createServer, type Server } from 'http';
import type { AddressInfo } from 'net';
import jwt from 'jsonwebtoken';
import pino from 'pino';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';
import { createCollabRouter } from '../http/routes';
import type { DocumentAccess, DocumentAccessChecker } from '../services/document-access';
import type { PublicPresenceInfo } from '../handlers/presence';

interface ActiveDocumentsBody {
  documents: Array<{ documentId: string; userCount: number }>;
  count: number;
}

const JWT_SECRET = 'test-secret-key-for-unit-tests';
const DOC_A = '11111111-1111-4111-8111-111111111111';
const DOC_B = '22222222-2222-4222-8222-222222222222';

const logger = pino({ level: 'silent' });

function token(sub: string, roles: string[] = ['USER'], secret = JWT_SECRET): string {
  return jwt.sign({ sub, email: `${sub}@example.com`, name: sub, roles }, secret, {
    expiresIn: '1h',
  }); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

describe('collab HTTP routes', () => {
  let server: Server;
  let baseUrl: string;
  let awareness: AwarenessService;
  let accessResult: DocumentAccess;
  const check = jest.fn<Promise<DocumentAccess>, [string, string, string]>();

  beforeAll(async () => {
    awareness = new AwarenessService(logger);
    const presenceHandler = new PresenceHandler(awareness, logger);
    const documentAccess: DocumentAccessChecker = { check };
    check.mockImplementation(async () => accessResult);

    const app = express();
    app.use(
      createCollabRouter({
        presenceHandler,
        documentAccess,
        jwtSecret: JWT_SECRET,
        logger,
      }),
    );
    server = createServer(app);
    await new Promise<void>((resolve) => server.listen(0, resolve));
    baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  afterAll(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  beforeEach(() => {
    check.mockClear();
    accessResult = 'allowed';
    awareness.addUser(DOC_A, 'sock-alice', 'alice', 'Alice', 'alice@acme.test');
    awareness.addUser(DOC_B, 'sock-bob', 'bob', 'Bob', 'bob@other.test');
  });

  afterEach(() => {
    awareness.removeUser('sock-alice');
    awareness.removeUser('sock-bob');
  });

  const get = (path: string, bearer?: string) =>
    fetch(`${baseUrl}${path}`, {
      headers: bearer ? { Authorization: `Bearer ${bearer}` } : {},
    });

  describe.each([
    `/api/v1/collab/documents`,
    `/api/v1/collab/documents/${DOC_A}/presence`,
  ])('%s', (path) => {
    it('returns 401 without a token', async () => {
      expect((await get(path)).status).toBe(401);
    });

    it('returns 401 for a token signed with another secret', async () => {
      expect((await get(path, token('mallory', ['USER'], 'wrong-secret'))).status).toBe(
        401,
      );
    });

    it('returns 401 for a refresh token', async () => {
      const refresh = jwt.sign({ sub: 'alice', type: 'refresh' }, JWT_SECRET, {
        expiresIn: '30d',
      }); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
      expect((await get(path, refresh)).status).toBe(401);
    });
  });

  describe('GET /api/v1/collab/documents/:id/presence', () => {
    it('returns presence without emails when the document-service allows access', async () => {
      const res = await get(`/api/v1/collab/documents/${DOC_A}/presence`, token('alice'));
      expect(res.status).toBe(200);
      const body = (await res.json()) as PublicPresenceInfo;
      expect(body.documentId).toBe(DOC_A);
      expect(body.count).toBe(1);
      expect(body.users[0].userId).toBe('alice');
      expect(body.users[0]).not.toHaveProperty('email');
      expect(JSON.stringify(body)).not.toContain('alice@acme.test');
      expect(check).toHaveBeenCalledWith(DOC_A, expect.any(String), 'alice');
    });

    it('returns 403 when the caller has no access to the document', async () => {
      accessResult = 'denied';
      const res = await get(
        `/api/v1/collab/documents/${DOC_A}/presence`,
        token('mallory'),
      );
      expect(res.status).toBe(403);
      expect(JSON.stringify(await res.json())).not.toContain('alice');
    });

    it('returns 404 when the document does not exist', async () => {
      accessResult = 'not_found';
      const res = await get(
        '/api/v1/collab/documents/not-a-real-document/presence',
        token('a'),
      );
      expect(res.status).toBe(404);
    });

    it('fails closed with 503 when access cannot be verified', async () => {
      accessResult = 'unavailable';
      const res = await get(`/api/v1/collab/documents/${DOC_A}/presence`, token('alice'));
      expect(res.status).toBe(503);
    });
  });

  describe('GET /api/v1/collab/documents', () => {
    it('lists only documents the caller is present in', async () => {
      const res = await get('/api/v1/collab/documents', token('alice'));
      expect(res.status).toBe(200);
      expect(await res.json()).toEqual({
        documents: [{ documentId: DOC_A, userCount: 1 }],
        count: 1,
      });
    });

    it('returns an empty list for a user who is not editing anything', async () => {
      const res = await get('/api/v1/collab/documents', token('mallory'));
      expect(await res.json()).toEqual({ documents: [], count: 0 });
    });

    it('lists every active document for admins', async () => {
      const res = await get('/api/v1/collab/documents', token('root', ['ADMIN']));
      const body = (await res.json()) as ActiveDocumentsBody;
      expect(body.count).toBe(2);
      expect(body.documents.map((d) => d.documentId).sort()).toEqual(
        [DOC_A, DOC_B].sort(),
      );
    });
  });
});
