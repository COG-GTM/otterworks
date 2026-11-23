import type { Logger } from 'pino';

export type DocumentAccess = 'write' | 'read' | 'none';

export interface DocumentAccessRequest {
  documentId: string;
  userId: string;
  token: string;
  shareToken?: string;
}

export interface DocumentPermissionChecker {
  checkAccess(request: DocumentAccessRequest): Promise<DocumentAccess>;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidDocumentId(documentId: unknown): documentId is string {
  return typeof documentId === 'string' && UUID_PATTERN.test(documentId);
}

/**
 * Resolves a caller's access to a document by asking the document-service,
 * which owns document ownership and share links. Owners get write access; a
 * valid read-only share token grants read access. Any error fails closed.
 */
export class DocumentServicePermissionChecker implements DocumentPermissionChecker {
  constructor(
    private readonly baseUrl: string,
    private readonly logger: Logger,
    private readonly timeoutMs = 5000,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async checkAccess(request: DocumentAccessRequest): Promise<DocumentAccess> {
    const { documentId, userId, token, shareToken } = request;
    if (!isValidDocumentId(documentId) || !token) return 'none';

    const id = encodeURIComponent(documentId);
    const ownerStatus = await this.get(`/api/v1/documents/${id}`, {
      Authorization: `Bearer ${token}`,
      'X-User-ID': userId,
    });
    if (ownerStatus === 200) return 'write';

    if (typeof shareToken === 'string' && shareToken.length > 0) {
      const query = new URLSearchParams({ document_id: documentId, token: shareToken });
      const shareStatus = await this.get(`/api/v1/documents/shared?${query}`, {});
      if (shareStatus === 200) return 'read';
    }

    this.logger.warn({ documentId, userId, ownerStatus }, 'document_access_denied');
    return 'none';
  }

  private async get(
    path: string,
    headers: Record<string, string>,
  ): Promise<number | null> {
    try {
      const res = await this.fetchImpl(`${this.baseUrl.replace(/\/+$/, '')}${path}`, {
        method: 'GET',
        headers,
        redirect: 'error',
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      // Only the status matters; release the connection instead of buffering the body.
      await res.body?.cancel().catch(() => undefined);
      return res.status;
    } catch (err) {
      this.logger.error(
        { err, path: path.split('?')[0] },
        'document_permission_lookup_failed',
      );
      return null;
    }
  }
}
