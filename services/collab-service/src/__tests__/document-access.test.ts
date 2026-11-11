import { createServer, type Server, type IncomingHttpHeaders } from 'http';
import type { AddressInfo } from 'net';
import pino from 'pino';
import { HttpDocumentAccessChecker } from '../services/document-access';

const DOC = '11111111-1111-4111-8111-111111111111';
const logger = pino({ level: 'silent' });

describe('HttpDocumentAccessChecker', () => {
  let server: Server;
  let baseUrl: string;
  let status = 200;
  let lastRequest: { url?: string; headers: IncomingHttpHeaders } | null = null;

  beforeAll(async () => {
    server = createServer((req, res) => {
      lastRequest = { url: req.url, headers: req.headers };
      res.statusCode = status;
      res.end('{}');
    });
    await new Promise<void>((resolve) => server.listen(0, resolve));
    baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  afterAll(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  beforeEach(() => {
    lastRequest = null;
  });

  it('forwards the caller token to the document-service', async () => {
    status = 200;
    const checker = new HttpDocumentAccessChecker(baseUrl, 1000, logger);
    await expect(checker.check(DOC, 'tok', 'alice')).resolves.toBe('allowed');
    expect(lastRequest?.url).toBe(`/api/v1/documents/${DOC}`);
    expect(lastRequest?.headers.authorization).toBe('Bearer tok');
    expect(lastRequest?.headers['x-user-id']).toBe('alice');
  });

  it.each([
    [401, 'denied'],
    [403, 'denied'],
    [404, 'not_found'],
    [422, 'not_found'],
    [500, 'unavailable'],
  ])('maps status %i to %s', async (code, expected) => {
    status = code;
    const checker = new HttpDocumentAccessChecker(baseUrl, 1000, logger);
    await expect(checker.check(DOC, 'tok', 'alice')).resolves.toBe(expected);
  });

  it('rejects non-UUID ids without calling the document-service', async () => {
    const checker = new HttpDocumentAccessChecker(baseUrl, 1000, logger);
    await expect(checker.check('../../admin', 'tok', 'alice')).resolves.toBe('not_found');
    expect(lastRequest).toBeNull();
  });

  it('fails closed when the document-service is unreachable', async () => {
    const checker = new HttpDocumentAccessChecker('http://127.0.0.1:1', 500, logger);
    await expect(checker.check(DOC, 'tok', 'alice')).resolves.toBe('unavailable');
  });
});
