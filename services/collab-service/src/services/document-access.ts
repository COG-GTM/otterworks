import type { Logger } from 'pino';

// Document ids are passed straight into URLs and room names, so only accept
// ids whose encoded form is identical to the raw value.
const DOCUMENT_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;

export function isValidDocumentId(documentId: unknown): documentId is string {
  return typeof documentId === 'string' && DOCUMENT_ID_PATTERN.test(documentId);
}

export interface DocumentAccessChecker {
  canAccess(documentId: string, userId: string, token: string): Promise<boolean>;
}

/**
 * Asks the document service whether the token's user may open a document.
 * Fails closed: any non-2xx response, timeout or network error denies access.
 */
export class HttpDocumentAccessChecker implements DocumentAccessChecker {
  constructor(
    private readonly documentServiceUrl: string,
    private readonly logger: Logger,
    private readonly timeoutMs = 3000,
  ) {}

  async canAccess(documentId: string, userId: string, token: string): Promise<boolean> {
    if (!isValidDocumentId(documentId) || !token) return false;

    const url = `${this.documentServiceUrl.replace(/\/+$/, '')}/api/v1/documents/${encodeURIComponent(documentId)}`;
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${token}`,
          'X-User-ID': userId,
        },
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      if (!response.ok) {
        this.logger.warn(
          { documentId, userId, status: response.status },
          'document_access_denied',
        );
        return false;
      }
      return true;
    } catch (err) {
      this.logger.error({ err, documentId, userId }, 'document_access_check_failed');
      return false;
    }
  }
}
