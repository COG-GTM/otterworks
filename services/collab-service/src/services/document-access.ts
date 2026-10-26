import type { Logger } from 'pino';

const DOCUMENT_ROOM_PATTERN =
  /^\/document-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

export type DocumentAccessResult = 'allowed' | 'denied' | 'unavailable';

/**
 * Returns the document id for a y-websocket room path of the form
 * `/document-<uuid>`, or null when the path names anything else.
 */
export function parseDocumentRoomPath(pathname: string): string | null {
  const match = DOCUMENT_ROOM_PATTERN.exec(pathname);
  return match ? match[1].toLowerCase() : null;
}

export function documentRoomName(documentId: string): string {
  return `document-${documentId}`;
}

export interface DocumentAccessCheckerOptions {
  documentServiceUrl: string;
  timeoutMs: number;
  fetchImpl?: typeof fetch;
}

/**
 * Asks document-service whether the bearer of `token` may open a document.
 * document-service enforces ownership on GET /api/v1/documents/:id, so a 2xx
 * means the caller is authorized; 401/403/404 mean they are not.
 */
export class DocumentAccessChecker {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(
    options: DocumentAccessCheckerOptions,
    private readonly logger: Logger,
  ) {
    this.baseUrl = options.documentServiceUrl.replace(/\/+$/, '');
    this.timeoutMs = options.timeoutMs;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async checkAccess(documentId: string, token: string): Promise<DocumentAccessResult> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetchImpl(
        `${this.baseUrl}/api/v1/documents/${encodeURIComponent(documentId)}`,
        {
          method: 'GET',
          headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
          signal: controller.signal,
        },
      );
      if (response.ok) return 'allowed';
      if ([400, 401, 403, 404, 422].includes(response.status)) return 'denied';
      this.logger.warn(
        { documentId, status: response.status },
        'document_access_check_unexpected_status',
      );
      return 'unavailable';
    } catch (err) {
      this.logger.warn(
        { documentId, error: (err as Error).message },
        'document_access_check_failed',
      );
      return 'unavailable';
    } finally {
      clearTimeout(timer);
    }
  }
}
