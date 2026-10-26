import type { Logger } from 'pino';

export interface DocumentAccessChecker {
  canAccess(documentId: string, token: string): Promise<boolean>;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidDocumentId(documentId: unknown): documentId is string {
  return typeof documentId === 'string' && UUID_PATTERN.test(documentId);
}

export interface HttpDocumentAccessCheckerOptions {
  baseUrl: string;
  timeoutMs: number;
}

/**
 * Asks document-service whether the caller may read a document, by fetching it
 * with the caller's own bearer token. Any non-2xx response or transport error
 * is treated as "no access" (fail closed).
 */
export class HttpDocumentAccessChecker implements DocumentAccessChecker {
  private baseUrl: string;
  private timeoutMs: number;
  private logger: Logger;

  constructor(options: HttpDocumentAccessCheckerOptions, logger: Logger) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.timeoutMs = options.timeoutMs;
    this.logger = logger;
  }

  async canAccess(documentId: string, token: string): Promise<boolean> {
    if (!isValidDocumentId(documentId) || !token) return false;

    const url = `${this.baseUrl}/api/v1/documents/${encodeURIComponent(documentId)}`;
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      if (!response.ok) {
        this.logger.debug(
          { documentId, status: response.status },
          'document_access_denied_by_document_service',
        );
      }
      return response.ok;
    } catch (err) {
      this.logger.error({ err, documentId }, 'document_access_check_failed');
      return false;
    }
  }
}
