import type { Logger } from 'pino';
import {
  DocumentAccessService,
  documentIdFromYjsRequestUrl,
  isValidDocumentId,
  normalizeDocumentId,
} from '../services/document-access';
import { extractBearerToken, isAdmin, userFromToken } from '../middleware/auth';
import jwt from 'jsonwebtoken';

const DOC_ID = '3f2b8c1e-7d4a-4c9b-9a1e-5b6c7d8e9f01';
const logger = { warn: jest.fn(), error: jest.fn() } as unknown as Logger;

function service(fetchImpl: jest.Mock, now: () => number = Date.now, cacheTtlMs = 30000) {
  return new DocumentAccessService({
    baseUrl: 'http://document-service:8083',
    timeoutMs: 50,
    cacheTtlMs,
    logger,
    fetchImpl: fetchImpl as unknown as typeof fetch,
    now,
  });
}

const respond = (status: number) => jest.fn().mockResolvedValue({ status });

describe('isValidDocumentId', () => {
  it('accepts UUIDs only', () => {
    expect(isValidDocumentId(DOC_ID)).toBe(true);
    expect(isValidDocumentId(DOC_ID.toUpperCase())).toBe(true);
    expect(isValidDocumentId('doc-1')).toBe(false);
    expect(isValidDocumentId(`${DOC_ID}/../x`)).toBe(false);
    expect(isValidDocumentId(undefined)).toBe(false);
    expect(isValidDocumentId(42)).toBe(false);
  });
});

describe('normalizeDocumentId', () => {
  it('lowercases UUIDs and rejects anything else', () => {
    expect(normalizeDocumentId(DOC_ID.toUpperCase())).toBe(DOC_ID);
    expect(normalizeDocumentId('doc-1')).toBeNull();
    expect(normalizeDocumentId(null)).toBeNull();
  });
});

describe('documentIdFromYjsRequestUrl', () => {
  it('maps document-<uuid> rooms to the document id', () => {
    expect(documentIdFromYjsRequestUrl(`/document-${DOC_ID}`)).toBe(DOC_ID);
    expect(documentIdFromYjsRequestUrl(`/document-${DOC_ID}?token=abc`)).toBe(DOC_ID);
  });

  it('rejects non-canonical casing so one document cannot get two rooms', () => {
    expect(documentIdFromYjsRequestUrl(`/document-${DOC_ID.toUpperCase()}`)).toBeNull();
  });

  it('rejects any other room name', () => {
    expect(documentIdFromYjsRequestUrl(undefined)).toBeNull();
    expect(documentIdFromYjsRequestUrl('/')).toBeNull();
    expect(documentIdFromYjsRequestUrl(`/${DOC_ID}`)).toBeNull();
    expect(documentIdFromYjsRequestUrl('/document-not-a-uuid')).toBeNull();
    expect(documentIdFromYjsRequestUrl(`/document-${DOC_ID}/extra`)).toBeNull();
    expect(documentIdFromYjsRequestUrl(`/x/document-${DOC_ID}`)).toBeNull();
  });
});

describe('DocumentAccessService', () => {
  afterEach(() => jest.clearAllMocks());

  it('asks document-service with the caller token and grants on 200', async () => {
    const fetchImpl = respond(200);
    await expect(service(fetchImpl).canAccess('tok', 'user-1', DOC_ID)).resolves.toBe(
      true,
    );

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`http://document-service:8083/api/v1/documents/${DOC_ID}`);
    expect(init.method).toBe('GET');
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(init.signal).toBeDefined();
  });

  it.each([401, 403, 404, 500, 503])(
    'denies when document-service returns %i',
    async (status) => {
      await expect(
        service(respond(status)).canAccess('tok', 'user-1', DOC_ID),
      ).resolves.toBe(false);
    },
  );

  it('fails closed on network errors', async () => {
    const fetchImpl = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));
    await expect(service(fetchImpl).canAccess('tok', 'user-1', DOC_ID)).resolves.toBe(
      false,
    );
    expect(logger.error).toHaveBeenCalled();
  });

  it('fails closed when document-service does not answer before the timeout', async () => {
    const fetchImpl = jest.fn(
      (_url: string, init: { signal: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          init.signal.addEventListener('abort', () => reject(new Error('aborted')));
        }),
    );
    await expect(service(fetchImpl).canAccess('tok', 'user-1', DOC_ID)).resolves.toBe(
      false,
    );
  });

  it('does not call document-service for invalid input', async () => {
    const fetchImpl = respond(200);
    const svc = service(fetchImpl);
    await expect(svc.canAccess('tok', 'user-1', 'not-a-uuid')).resolves.toBe(false);
    await expect(svc.canAccess('', 'user-1', DOC_ID)).resolves.toBe(false);
    await expect(svc.canAccess('tok', '', DOC_ID)).resolves.toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('caches grants per user until the TTL expires', async () => {
    let now = 1000;
    const fetchImpl = respond(200);
    const svc = service(fetchImpl, () => now, 5000);

    await svc.canAccess('tok', 'user-1', DOC_ID);
    await svc.canAccess('tok', 'user-1', DOC_ID);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    await svc.canAccess('tok2', 'user-2', DOC_ID);
    expect(fetchImpl).toHaveBeenCalledTimes(2);

    now += 5001;
    fetchImpl.mockResolvedValue({ status: 403 });
    await expect(svc.canAccess('tok', 'user-1', DOC_ID)).resolves.toBe(false);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it('never caches denials', async () => {
    const fetchImpl = respond(403);
    const svc = service(fetchImpl);
    await svc.canAccess('tok', 'user-1', DOC_ID);
    fetchImpl.mockResolvedValue({ status: 200 });
    await expect(svc.canAccess('tok', 'user-1', DOC_ID)).resolves.toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});

describe('auth helpers', () => {
  const secret = 'test-secret';

  it('extracts bearer tokens', () => {
    expect(extractBearerToken('Bearer abc')).toBe('abc');
    expect(extractBearerToken('Bearer ')).toBeUndefined();
    expect(extractBearerToken('Basic abc')).toBeUndefined();
    expect(extractBearerToken(undefined)).toBeUndefined();
  });

  it('requires a subject claim', () => {
    expect(() => userFromToken(jwt.sign({ email: 'a@b.c' }, secret), secret)).toThrow();
    expect(
      userFromToken(jwt.sign({ sub: 'u1', roles: ['USER'] }, secret), secret).userId,
    ).toBe('u1');
  });

  it('recognises admins only by role', () => {
    expect(isAdmin({ userId: 'u', email: '', displayName: '', roles: ['ADMIN'] })).toBe(
      true,
    );
    expect(
      isAdmin({ userId: 'u', email: '', displayName: '', roles: ['ROLE_ADMIN'] }),
    ).toBe(true);
    expect(
      isAdmin({ userId: 'u', email: '', displayName: '', roles: ['USER', 'EDITOR'] }),
    ).toBe(false);
  });
});
