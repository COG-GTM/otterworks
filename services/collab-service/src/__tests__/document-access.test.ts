import {
  DocumentAccessChecker,
  documentRoomName,
  parseDocumentRoomPath,
} from '../services/document-access';

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

const DOC_ID = '3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b';

describe('parseDocumentRoomPath', () => {
  it('extracts the document id from a valid room path', () => {
    expect(parseDocumentRoomPath(`/document-${DOC_ID}`)).toBe(DOC_ID);
    expect(parseDocumentRoomPath(`/document-${DOC_ID.toUpperCase()}`)).toBe(DOC_ID);
  });

  it.each([
    '/',
    '/document-',
    '/document-not-a-uuid',
    `/document-${DOC_ID}/extra`,
    `/other-${DOC_ID}`,
    `/document-${DOC_ID}x`,
    `//document-${DOC_ID}`,
    `/document-${DOC_ID}%00`,
  ])('rejects %s', (path) => {
    expect(parseDocumentRoomPath(path)).toBeNull();
  });

  it('builds the room name used by the client', () => {
    expect(documentRoomName(DOC_ID)).toBe(`document-${DOC_ID}`);
  });
});

describe('DocumentAccessChecker', () => {
  const makeChecker = (fetchImpl: jest.Mock) =>
    new DocumentAccessChecker(
      {
        documentServiceUrl: 'http://document-service:8083/',
        timeoutMs: 1000,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      },
      mockLogger,
    );

  it('forwards the caller token to document-service and allows on 200', async () => {
    const fetchImpl = jest.fn().mockResolvedValue({ ok: true, status: 200 });
    const result = await makeChecker(fetchImpl).checkAccess(DOC_ID, 'tok');
    expect(result).toBe('allowed');
    expect(fetchImpl).toHaveBeenCalledWith(
      `http://document-service:8083/api/v1/documents/${DOC_ID}`,
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Authorization: 'Bearer tok' }),
      }),
    );
  });

  it.each([401, 403, 404, 422])('denies on %d', async (status) => {
    const fetchImpl = jest.fn().mockResolvedValue({ ok: false, status });
    const result = await makeChecker(fetchImpl).checkAccess(DOC_ID, 'tok');
    expect(result).toBe('denied');
  });

  it('fails closed on server errors', async () => {
    const fetchImpl = jest.fn().mockResolvedValue({ ok: false, status: 502 });
    const result = await makeChecker(fetchImpl).checkAccess(DOC_ID, 'tok');
    expect(result).toBe('unavailable');
  });

  it('fails closed when document-service is unreachable', async () => {
    const fetchImpl = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));
    const result = await makeChecker(fetchImpl).checkAccess(DOC_ID, 'tok');
    expect(result).toBe('unavailable');
  });
});
