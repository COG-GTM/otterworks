import { DocumentServicePermissionChecker } from '../services/document-permissions';

const DOC_ID = '3f2b8c1e-6a4d-4e5f-9b7a-1c2d3e4f5a6b';

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

function fakeFetch(statuses: Record<string, number>) {
  return jest.fn(async (url: string | URL | Request) => {
    const path = new URL(String(url)).pathname;
    if (!(path in statuses)) throw new Error(`unexpected ${path}`);
    return new Response(null, { status: statuses[path] });
  }) as unknown as jest.MockedFunction<typeof fetch>;
}

describe('DocumentServicePermissionChecker', () => {
  it('grants write access when the document-service returns the document', async () => {
    const fetchImpl = fakeFetch({ [`/api/v1/documents/${DOC_ID}`]: 200 });
    const checker = new DocumentServicePermissionChecker(
      'http://document-service:8083/',
      mockLogger,
      1000,
      fetchImpl,
    );

    await expect(
      checker.checkAccess({ documentId: DOC_ID, userId: 'u1', token: 'jwt' }),
    ).resolves.toBe('write');

    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe(`http://document-service:8083/api/v1/documents/${DOC_ID}`);
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer jwt');
  });

  it('denies non-owners without a share token', async () => {
    const fetchImpl = fakeFetch({ [`/api/v1/documents/${DOC_ID}`]: 403 });
    const checker = new DocumentServicePermissionChecker(
      'http://ds',
      mockLogger,
      1000,
      fetchImpl,
    );

    await expect(
      checker.checkAccess({ documentId: DOC_ID, userId: 'u2', token: 'jwt' }),
    ).resolves.toBe('none');
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('grants read access for a valid share token and none for an invalid one', async () => {
    const valid = fakeFetch({
      [`/api/v1/documents/${DOC_ID}`]: 403,
      '/api/v1/documents/shared': 200,
    });
    const checker = new DocumentServicePermissionChecker(
      'http://ds',
      mockLogger,
      1000,
      valid,
    );
    await expect(
      checker.checkAccess({
        documentId: DOC_ID,
        userId: 'u2',
        token: 'jwt',
        shareToken: 'abc',
      }),
    ).resolves.toBe('read');
    const sharedUrl = new URL(String(valid.mock.calls[1][0]));
    expect(sharedUrl.searchParams.get('document_id')).toBe(DOC_ID);
    expect(sharedUrl.searchParams.get('token')).toBe('abc');

    const invalid = fakeFetch({
      [`/api/v1/documents/${DOC_ID}`]: 403,
      '/api/v1/documents/shared': 403,
    });
    const checker2 = new DocumentServicePermissionChecker(
      'http://ds',
      mockLogger,
      1000,
      invalid,
    );
    await expect(
      checker2.checkAccess({
        documentId: DOC_ID,
        userId: 'u2',
        token: 'jwt',
        shareToken: 'bad',
      }),
    ).resolves.toBe('none');
  });

  it('rejects non-UUID document ids without calling the document-service', async () => {
    const fetchImpl = fakeFetch({});
    const checker = new DocumentServicePermissionChecker(
      'http://ds',
      mockLogger,
      1000,
      fetchImpl,
    );

    for (const documentId of ['../admin', `${DOC_ID}/versions`, 'doc-1', '']) {
      await expect(
        checker.checkAccess({ documentId, userId: 'u1', token: 'jwt' }),
      ).resolves.toBe('none');
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('fails closed when the document-service is unreachable', async () => {
    const fetchImpl = jest.fn(async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    const checker = new DocumentServicePermissionChecker(
      'http://ds',
      mockLogger,
      1000,
      fetchImpl,
    );

    await expect(
      checker.checkAccess({ documentId: DOC_ID, userId: 'u1', token: 'jwt' }),
    ).resolves.toBe('none');
  });
});
