import {
  HttpDocumentAccessChecker,
  isValidDocumentId,
} from '../services/document-access';

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

describe('HttpDocumentAccessChecker', () => {
  const fetchMock = jest.fn();
  const checker = new HttpDocumentAccessChecker(
    'http://document-service:8083/',
    mockLogger,
  );
  const docId = '3f1c2a4e-0b7d-4c8e-9a51-6d2f0e8b7c11';

  beforeEach(() => {
    fetchMock.mockReset();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it('allows access when the document service returns the document', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200 });

    await expect(checker.canAccess(docId, 'user-1', 'tok')).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://document-service:8083/api/v1/documents/${docId}`,
      expect.objectContaining({
        method: 'GET',
        headers: { Authorization: 'Bearer tok', 'X-User-ID': 'user-1' },
      }),
    );
  });

  it.each([401, 403, 404, 422, 500])('denies access on HTTP %i', async (status) => {
    fetchMock.mockResolvedValue({ ok: false, status });
    await expect(checker.canAccess(docId, 'user-1', 'tok')).resolves.toBe(false);
  });

  it('denies access when the document service is unreachable', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
    await expect(checker.canAccess(docId, 'user-1', 'tok')).resolves.toBe(false);
  });

  it('denies malformed ids and missing tokens without calling the document service', async () => {
    await expect(checker.canAccess('../admin', 'user-1', 'tok')).resolves.toBe(false);
    await expect(checker.canAccess(docId, 'user-1', '')).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('isValidDocumentId', () => {
  it.each(['abc', 'doc-1', '3f1c2a4e-0b7d-4c8e-9a51-6d2f0e8b7c11'])(
    'accepts %s',
    (id) => {
      expect(isValidDocumentId(id)).toBe(true);
    },
  );

  it.each(['', '../x', 'a/b', 'a?b', 'a%2Fb', 'x'.repeat(129), 42, undefined, null])(
    'rejects %p',
    (id) => {
      expect(isValidDocumentId(id)).toBe(false);
    },
  );
});
