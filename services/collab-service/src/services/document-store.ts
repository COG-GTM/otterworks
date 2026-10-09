import { v4 as uuidv4 } from 'uuid';
import type { Logger } from 'pino';
import { RedisAdapter } from './redis-adapter';

const DOC_STATE_KEY = 'doc:state:';
const DOC_SNAPSHOTS_KEY = 'doc:snapshots:';
const DOC_META_KEY = 'doc:meta:';

export class DocumentTooLargeError extends Error {
  constructor(
    readonly documentId: string,
    readonly bytes: number,
    readonly maxBytes: number,
  ) {
    super(`Document ${documentId} state is ${bytes} bytes (limit ${maxBytes})`);
    this.name = 'DocumentTooLargeError';
  }
}

export interface DocumentSnapshot {
  id: string;
  documentId: string;
  state: string; // base64-encoded Yjs state
  createdAt: string;
  createdBy: string;
  label?: string;
}

export interface DocumentMeta {
  documentId: string;
  createdAt: string;
  lastModifiedAt: string;
  lastModifiedBy: string;
  version: number;
}

export class DocumentStore {
  private redis: RedisAdapter;
  private logger: Logger;
  private documentTtl: number;
  private snapshotTtl: number;
  private maxSnapshots: number;
  private maxStateBytes: number | undefined;
  private maxSnapshotBytes: number | undefined;

  constructor(
    redis: RedisAdapter,
    logger: Logger,
    options?: {
      documentTtl?: number;
      snapshotTtl?: number;
      maxSnapshots?: number;
      /** Reject document states / snapshots larger than this many bytes. */
      maxStateBytes?: number;
      /** Upper bound on the serialized size of all snapshots kept per document. */
      maxSnapshotBytes?: number;
    },
  ) {
    this.redis = redis;
    this.logger = logger;
    this.documentTtl = options?.documentTtl ?? 86400;
    this.snapshotTtl = options?.snapshotTtl ?? 604800;
    this.maxSnapshots = options?.maxSnapshots ?? 50;
    this.maxStateBytes = options?.maxStateBytes;
    this.maxSnapshotBytes = options?.maxSnapshotBytes;
  }

  private assertStateSize(documentId: string, state: Buffer): void {
    if (this.maxStateBytes !== undefined && state.length > this.maxStateBytes) {
      throw new DocumentTooLargeError(documentId, state.length, this.maxStateBytes);
    }
  }

  async getDocumentState(documentId: string): Promise<Uint8Array | null> {
    const data = await this.redis.get(`${DOC_STATE_KEY}${documentId}`);
    if (!data) return null;
    return new Uint8Array(data);
  }

  async saveDocumentState(
    documentId: string,
    state: Buffer,
    userId?: string,
  ): Promise<void> {
    this.assertStateSize(documentId, state);
    await this.redis.set(`${DOC_STATE_KEY}${documentId}`, state, this.documentTtl);

    // Update document metadata
    const now = new Date().toISOString();
    const metaKey = `${DOC_META_KEY}${documentId}`;

    await this.redis.hset(metaKey, 'documentId', documentId);
    await this.redis.hset(metaKey, 'lastModifiedAt', now);
    await this.redis.hset(metaKey, 'lastModifiedBy', userId || 'system');
    // Use atomic hincrby to avoid lost increments under concurrent updates
    const version = await this.redis.hincrby(metaKey, 'version', 1);

    const createdAt = await this.redis.hget(metaKey, 'createdAt');
    if (!createdAt) {
      await this.redis.hset(metaKey, 'createdAt', now);
    }

    await this.redis.expire(metaKey, this.documentTtl);

    this.logger.debug({ documentId, version }, 'document_state_saved');
  }

  async deleteDocumentState(documentId: string): Promise<void> {
    await this.redis.del(`${DOC_STATE_KEY}${documentId}`);
    await this.redis.del(`${DOC_META_KEY}${documentId}`);
    await this.redis.del(`${DOC_SNAPSHOTS_KEY}${documentId}`);
    this.logger.info({ documentId }, 'document_state_deleted');
  }

  async getDocumentMeta(documentId: string): Promise<DocumentMeta | null> {
    const data = await this.redis.hgetall(`${DOC_META_KEY}${documentId}`);
    if (!data || !data.documentId) return null;
    return {
      documentId: data.documentId,
      createdAt: data.createdAt,
      lastModifiedAt: data.lastModifiedAt,
      lastModifiedBy: data.lastModifiedBy,
      version: parseInt(data.version, 10),
    };
  }

  async createSnapshot(
    documentId: string,
    state: Buffer,
    createdBy: string,
    label?: string,
  ): Promise<DocumentSnapshot> {
    this.assertStateSize(documentId, state);
    const snapshot: DocumentSnapshot = {
      id: uuidv4(),
      documentId,
      state: state.toString('base64'),
      createdAt: new Date().toISOString(),
      createdBy,
      label,
    };

    const key = `${DOC_SNAPSHOTS_KEY}${documentId}`;
    await this.redis.lpush(key, JSON.stringify(snapshot));

    // Trim to max snapshots, and to the per-document byte budget if one is set
    const count = await this.redis.llen(key);
    let keep = this.maxSnapshots;
    if (this.maxSnapshotBytes !== undefined && count > 1) {
      keep = await this.snapshotsWithinBudget(key, this.maxSnapshotBytes);
    }
    if (count > keep) {
      await this.redis.ltrim(key, 0, keep - 1);
    }

    await this.redis.expire(key, this.snapshotTtl);

    this.logger.info(
      { documentId, snapshotId: snapshot.id, createdBy },
      'document_snapshot_created',
    );

    return snapshot;
  }

  private async snapshotsWithinBudget(key: string, maxBytes: number): Promise<number> {
    const entries = await this.redis.lrange(key, 0, this.maxSnapshots - 1);
    let total = 0;
    let keep = 0;
    for (const entry of entries) {
      total += Buffer.byteLength(entry);
      // Always keep the newest snapshot, even if it alone exceeds the budget
      if (keep > 0 && total > maxBytes) break;
      keep += 1;
    }
    return Math.max(keep, 1);
  }

  async getSnapshots(documentId: string, limit = 20): Promise<DocumentSnapshot[]> {
    const key = `${DOC_SNAPSHOTS_KEY}${documentId}`;
    const raw = await this.redis.lrange(key, 0, limit - 1);
    return raw.map((item) => JSON.parse(item) as DocumentSnapshot);
  }

  async getSnapshotState(
    documentId: string,
    snapshotId: string,
  ): Promise<Uint8Array | null> {
    const snapshots = await this.getSnapshots(documentId, this.maxSnapshots);
    const snapshot = snapshots.find((s) => s.id === snapshotId);
    if (!snapshot) return null;
    return new Uint8Array(Buffer.from(snapshot.state, 'base64'));
  }
}
