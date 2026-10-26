import type { Logger } from 'pino';

export type DocumentAccess = 'allowed' | 'denied' | 'unavailable';

export interface DocumentAccessChecker {
  check(documentId: string, authorization: string): Promise<DocumentAccess>;
}

const DENIED_STATUSES = new Set([400, 401, 403, 404, 422]);

/**
 * Asks document-service whether the caller may read a document, by replaying the
 * caller's own bearer token against GET /api/v1/documents/:id. document-service
 * owns the ownership rules, so collab-service never decides access itself.
 */
export class HttpDocumentAccessChecker implements DocumentAccessChecker {
  constructor(
    private readonly baseUrl: string,
    private readonly timeoutMs: number,
    private readonly logger: Logger,
  ) {}

  async check(documentId: string, authorization: string): Promise<DocumentAccess> {
    const url = `${this.baseUrl.replace(
      /\/+$/,
      '',
    )}/api/v1/documents/${encodeURIComponent(documentId)}`;
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: { Authorization: authorization, Accept: 'application/json' },
        redirect: 'manual',
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      if (response.status === 200) return 'allowed';
      if (DENIED_STATUSES.has(response.status)) return 'denied';
      this.logger.warn(
        { documentId, status: response.status },
        'document_access_check_unexpected_status',
      );
      return 'unavailable';
    } catch (err) {
      this.logger.error(
        { documentId, error: (err as Error).message },
        'document_access_check_failed',
      );
      return 'unavailable';
    }
  }
}
