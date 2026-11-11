import type { Logger } from 'pino';

export type DocumentAccess = 'allowed' | 'denied' | 'not_found' | 'unavailable';

export interface DocumentAccessChecker {
  check(documentId: string, token: string, userId: string): Promise<DocumentAccess>;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidDocumentId(documentId: string): boolean {
  return UUID_PATTERN.test(documentId);
}

/**
 * Asks the document-service, which owns document authorization, whether the
 * caller may read a document. The caller's own token is forwarded so the
 * document-service applies its normal ownership checks.
 */
export class HttpDocumentAccessChecker implements DocumentAccessChecker {
  constructor(
    private readonly baseUrl: string,
    private readonly timeoutMs: number,
    private readonly logger: Logger,
  ) {}

  async check(
    documentId: string,
    token: string,
    userId: string,
  ): Promise<DocumentAccess> {
    if (!isValidDocumentId(documentId)) {
      return 'not_found';
    }

    const url = `${this.baseUrl.replace(/\/+$/, '')}/api/v1/documents/${encodeURIComponent(documentId)}`;
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${token}`,
          'X-User-ID': userId,
          Accept: 'application/json',
        },
        signal: AbortSignal.timeout(this.timeoutMs),
      });

      if (response.ok) return 'allowed';
      if (response.status === 401 || response.status === 403) return 'denied';
      if (response.status === 404 || response.status === 422) return 'not_found';

      this.logger.warn(
        { documentId, status: response.status },
        'document_access_check_unexpected_status',
      );
      return 'unavailable';
    } catch (err) {
      this.logger.error({ err, documentId }, 'document_access_check_failed');
      return 'unavailable';
    }
  }
}
