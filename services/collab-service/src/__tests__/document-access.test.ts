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

const DOC_ID = '3f2b8c1e-5a4d-4e6f-9b7a-1c2d3e4f5a6b';

describe('HttpDocumentAccessChecker', () => {
  const originalFetch = global.fetch;
  let fetchMock: jest.Mock;
  let checker: HttpDocumentAccessChecker;

  beforeEach(() => {
    fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    checker = new HttpDocumentAccessChecker(
      { baseUrl: 'http://document-service:8083/', timeoutMs: 1000 },
      mockLogger,
    );
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('asks document-service with the caller token and allows on 200', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200 });

    await expect(checker.canAccess(DOC_ID, 'user-token')).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://document-service:8083/api/v1/documents/${DOC_ID}`,
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Authorization: 'Bearer user-token' }),
      }),
    );
  });

  it.each([401, 403, 404, 500])(
    'denies when document-service returns %i',
    async (status) => {
      fetchMock.mockResolvedValue({ ok: false, status });
      await expect(checker.canAccess(DOC_ID, 'user-token')).resolves.toBe(false);
    },
  );

  it('denies when document-service is unreachable', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
    await expect(checker.canAccess(DOC_ID, 'user-token')).resolves.toBe(false);
  });

  it('denies malformed document ids without calling document-service', async () => {
    await expect(checker.canAccess('../admin', 'user-token')).resolves.toBe(false);
    const nested = `${DOC_ID}/versions`;
    await expect(checker.canAccess(nested, 'user-token')).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('denies when no token is available', async () => {
    await expect(checker.canAccess(DOC_ID, '')).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('isValidDocumentId', () => {
  it('accepts UUIDs only', () => {
    expect(isValidDocumentId(DOC_ID)).toBe(true);
    expect(isValidDocumentId('doc-1')).toBe(false);
    expect(isValidDocumentId(undefined)).toBe(false);
  });
});
