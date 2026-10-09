import type { Logger } from 'pino';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// Lowercase only: y-websocket keys rooms by the raw URL path, so accepting other
// casings would split one document's state across several rooms.
const YJS_ROOM_PATTERN =
  /^document-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/;
const MAX_CACHE_ENTRIES = 10000;

export function isValidDocumentId(documentId: unknown): documentId is string {
  return typeof documentId === 'string' && UUID_PATTERN.test(documentId);
}

/** Canonical (lowercase) document id, or null if the value is not a UUID. */
export function normalizeDocumentId(documentId: unknown): string | null {
  return isValidDocumentId(documentId) ? documentId.toLowerCase() : null;
}

/**
 * Maps a y-websocket request URL to the document UUID it addresses. y-websocket
 * derives its room name from `req.url.slice(1).split('?')[0]`, so the same
 * expression is validated here; anything other than `document-<uuid>` is rejected.
 */
export function documentIdFromYjsRequestUrl(
  requestUrl: string | undefined,
): string | null {
  if (!requestUrl) return null;
  const docName = requestUrl.slice(1).split('?')[0];
  const match = YJS_ROOM_PATTERN.exec(docName);
  return match ? match[1] : null;
}

export interface AccessCheckOptions {
  /** Skip the grant cache, e.g. when revalidating an already-open session. */
  fresh?: boolean;
}

export interface DocumentAccessChecker {
  canAccess(
    accessToken: string,
    userId: string,
    documentId: string,
    options?: AccessCheckOptions,
  ): Promise<boolean>;
}

export interface DocumentAccessOptions {
  baseUrl: string;
  timeoutMs: number;
  cacheTtlMs: number;
  logger: Logger;
  fetchImpl?: typeof fetch;
  now?: () => number;
}

/**
 * Asks document-service whether the caller may open a document by replaying the
 * caller's own token against `GET /api/v1/documents/:id`, which enforces the
 * owner check. Only a 200 grants access; every other status or error denies.
 */
export class DocumentAccessService implements DocumentAccessChecker {
  private readonly allowed = new Map<string, number>();
  private readonly fetchImpl: typeof fetch;
  private readonly now: () => number;

  constructor(private readonly options: DocumentAccessOptions) {
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.now = options.now ?? Date.now;
  }

  async canAccess(
    accessToken: string,
    userId: string,
    documentId: string,
    options: AccessCheckOptions = {},
  ): Promise<boolean> {
    if (!accessToken || !userId || !isValidDocumentId(documentId)) return false;

    const cacheKey = `${userId}:${documentId.toLowerCase()}`;
    const expiresAt = this.allowed.get(cacheKey);
    if (expiresAt !== undefined) {
      if (!options.fresh && expiresAt > this.now()) return true;
      this.allowed.delete(cacheKey);
    }

    const { baseUrl, timeoutMs, logger } = this.options;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await this.fetchImpl(
        `${baseUrl}/api/v1/documents/${encodeURIComponent(documentId)}`,
        {
          method: 'GET',
          headers: {
            Authorization: `Bearer ${accessToken}`,
            'X-User-ID': userId,
            Accept: 'application/json',
          },
          signal: controller.signal,
        },
      );
      if (response.status === 200) {
        this.remember(cacheKey);
        return true;
      }
      logger.warn(
        { documentId, userId, status: response.status },
        'document_access_denied',
      );
      return false;
    } catch (err) {
      logger.error(
        { documentId, userId, error: (err as Error).message },
        'document_access_check_failed',
      );
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  private remember(cacheKey: string): void {
    if (this.options.cacheTtlMs <= 0) return;
    this.allowed.delete(cacheKey);
    if (this.allowed.size >= MAX_CACHE_ENTRIES) {
      const oldest = this.allowed.keys().next().value;
      if (oldest !== undefined) this.allowed.delete(oldest);
    }
    this.allowed.set(cacheKey, this.now() + this.options.cacheTtlMs);
  }
}
