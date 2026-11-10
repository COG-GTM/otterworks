import type { IncomingMessage } from 'http';
import jwt from 'jsonwebtoken';
import { authorizeYjsUpgrade, parseYjsDocumentId } from '../middleware/yjs-auth';
import type {
  DocumentAccess,
  DocumentPermissionChecker,
} from '../services/document-permissions';

const JWT_SECRET = 'test-secret-key-for-unit-tests';
const DOC_ID = '3f2b8c1e-6a4d-4e5f-9b7a-1c2d3e4f5a6b';

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

function token(sub: string): string {
  return jwt.sign({ sub }, JWT_SECRET, { expiresIn: '1h' }); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

function request(url: string, headers: Record<string, string> = {}): IncomingMessage {
  return { url, headers } as unknown as IncomingMessage;
}

function checker(access: DocumentAccess): jest.Mocked<DocumentPermissionChecker> {
  return { checkAccess: jest.fn().mockResolvedValue(access) };
}

describe('parseYjsDocumentId', () => {
  it('extracts the id from the y-websocket room path', () => {
    expect(parseYjsDocumentId(`/document-${DOC_ID}?token=x`)).toBe(DOC_ID);
    expect(parseYjsDocumentId('/other-room')).toBeNull();
    expect(parseYjsDocumentId(undefined)).toBeNull();
  });
});

describe('authorizeYjsUpgrade', () => {
  it('rejects missing and invalid tokens with 401', async () => {
    const perms = checker('write');
    await expect(
      authorizeYjsUpgrade(request(`/document-${DOC_ID}`), JWT_SECRET, perms, mockLogger),
    ).resolves.toEqual({ allowed: false, status: 401 });
    await expect(
      authorizeYjsUpgrade(
        request(`/document-${DOC_ID}?token=garbage`),
        JWT_SECRET,
        perms,
        mockLogger,
      ),
    ).resolves.toEqual({ allowed: false, status: 401 });
    expect(perms.checkAccess).not.toHaveBeenCalled();
  });

  it('rejects users without edit access to the room document with 403', async () => {
    for (const access of ['none', 'read'] as const) {
      const perms = checker(access);
      const t = token('mallory');
      await expect(
        authorizeYjsUpgrade(
          request(`/document-${DOC_ID}?token=${t}`),
          JWT_SECRET,
          perms,
          mockLogger,
        ),
      ).resolves.toEqual({ allowed: false, status: 403 });
      expect(perms.checkAccess).toHaveBeenCalledWith({
        documentId: DOC_ID,
        userId: 'mallory',
        token: t,
      });
    }
  });

  it('rejects rooms that do not name a document', async () => {
    const perms = checker('write');
    await expect(
      authorizeYjsUpgrade(
        request(`/arbitrary-room?token=${token('alice')}`),
        JWT_SECRET,
        perms,
        mockLogger,
      ),
    ).resolves.toEqual({ allowed: false, status: 403 });
    expect(perms.checkAccess).not.toHaveBeenCalled();
  });

  it('allows owners, including via the Authorization header', async () => {
    const perms = checker('write');
    await expect(
      authorizeYjsUpgrade(
        request(`/document-${DOC_ID}`, { authorization: `Bearer ${token('alice')}` }),
        JWT_SECRET,
        perms,
        mockLogger,
      ),
    ).resolves.toEqual({ allowed: true, documentId: DOC_ID, userId: 'alice' });
  });
});
