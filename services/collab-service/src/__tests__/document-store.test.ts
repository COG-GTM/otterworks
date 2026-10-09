import * as Y from 'yjs';
import { DocumentStore, DocumentTooLargeError } from '../services/document-store';
import { RedisAdapter } from '../services/redis-adapter';

// Mock RedisAdapter
const mockRedis = {
  get: jest.fn(),
  set: jest.fn(),
  del: jest.fn(),
  hset: jest.fn(),
  hget: jest.fn(),
  hgetall: jest.fn(),
  hdel: jest.fn(),
  hincrby: jest.fn(),
  lpush: jest.fn(),
  lrange: jest.fn(),
  ltrim: jest.fn(),
  llen: jest.fn(),
  expire: jest.fn(),
  publish: jest.fn(),
  subscribe: jest.fn(),
  connect: jest.fn(),
  disconnect: jest.fn(),
  ping: jest.fn(),
} as unknown as jest.Mocked<RedisAdapter>;

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
  fatal: jest.fn(),
  trace: jest.fn(),
  child: jest.fn().mockReturnThis(),
  level: 'info',
} as never;

describe('DocumentStore', () => {
  let store: DocumentStore;

  beforeEach(() => {
    jest.clearAllMocks();
    store = new DocumentStore(mockRedis, mockLogger, {
      documentTtl: 86400,
      snapshotTtl: 604800,
      maxSnapshots: 50,
    });
  });

  describe('getDocumentState', () => {
    it('should return null when no document exists', async () => {
      mockRedis.get.mockResolvedValue(null);

      const result = await store.getDocumentState('doc-123');

      expect(result).toBeNull();
      expect(mockRedis.get).toHaveBeenCalledWith('doc:state:doc-123');
    });

    it('should return Uint8Array when document exists', async () => {
      const doc = new Y.Doc();
      doc.getText('content').insert(0, 'Hello, world!');
      const state = Y.encodeStateAsUpdate(doc);
      const buffer = Buffer.from(state);

      mockRedis.get.mockResolvedValue(buffer);

      const result = await store.getDocumentState('doc-123');

      expect(result).toBeInstanceOf(Uint8Array);
      expect(result).not.toBeNull();

      // Verify we can reconstruct the doc from the returned state
      const reconstructed = new Y.Doc();
      Y.applyUpdate(reconstructed, result!);
      expect(reconstructed.getText('content').toString()).toBe('Hello, world!');
    });
  });

  describe('saveDocumentState', () => {
    it('should save document state with TTL', async () => {
      mockRedis.set.mockResolvedValue(undefined);
      mockRedis.hset.mockResolvedValue(undefined);
      mockRedis.hincrby.mockResolvedValue(1);
      mockRedis.hget.mockResolvedValue(null);
      mockRedis.expire.mockResolvedValue(undefined);

      const doc = new Y.Doc();
      doc.getText('content').insert(0, 'Test content');
      const state = Buffer.from(Y.encodeStateAsUpdate(doc));

      await store.saveDocumentState('doc-456', state, 'user-1');

      expect(mockRedis.set).toHaveBeenCalledWith('doc:state:doc-456', state, 86400);
    });

    it('should update document metadata', async () => {
      mockRedis.set.mockResolvedValue(undefined);
      mockRedis.hset.mockResolvedValue(undefined);
      mockRedis.hincrby.mockResolvedValue(6);
      mockRedis.hget.mockResolvedValue('2024-01-01T00:00:00Z');
      mockRedis.expire.mockResolvedValue(undefined);

      const state = Buffer.from(new Uint8Array([1, 2, 3]));
      await store.saveDocumentState('doc-456', state, 'user-1');

      expect(mockRedis.hincrby).toHaveBeenCalledWith('doc:meta:doc-456', 'version', 1);
      expect(mockRedis.hset).toHaveBeenCalledWith(
        'doc:meta:doc-456',
        'lastModifiedBy',
        'user-1',
      );
    });

    it('should set createdAt on first save', async () => {
      mockRedis.set.mockResolvedValue(undefined);
      mockRedis.hset.mockResolvedValue(undefined);
      mockRedis.hincrby.mockResolvedValue(1);
      mockRedis.hget.mockResolvedValue(null);
      mockRedis.expire.mockResolvedValue(undefined);

      const state = Buffer.from(new Uint8Array([1, 2, 3]));
      await store.saveDocumentState('doc-new', state);

      expect(mockRedis.hset).toHaveBeenCalledWith(
        'doc:meta:doc-new',
        'createdAt',
        expect.any(String),
      );
    });

    it('should default userId to system when not provided', async () => {
      mockRedis.set.mockResolvedValue(undefined);
      mockRedis.hset.mockResolvedValue(undefined);
      mockRedis.hincrby.mockResolvedValue(1);
      mockRedis.hget.mockResolvedValue(null);
      mockRedis.expire.mockResolvedValue(undefined);

      const state = Buffer.from(new Uint8Array([1, 2, 3]));
      await store.saveDocumentState('doc-456', state);

      expect(mockRedis.hset).toHaveBeenCalledWith(
        'doc:meta:doc-456',
        'lastModifiedBy',
        'system',
      );
    });
  });

  describe('deleteDocumentState', () => {
    it('should delete all keys for a document', async () => {
      mockRedis.del.mockResolvedValue(undefined);

      await store.deleteDocumentState('doc-789');

      expect(mockRedis.del).toHaveBeenCalledWith('doc:state:doc-789');
      expect(mockRedis.del).toHaveBeenCalledWith('doc:meta:doc-789');
      expect(mockRedis.del).toHaveBeenCalledWith('doc:snapshots:doc-789');
      expect(mockRedis.del).toHaveBeenCalledTimes(3);
    });
  });

  describe('getDocumentMeta', () => {
    it('should return null when no metadata exists', async () => {
      mockRedis.hgetall.mockResolvedValue({});

      const result = await store.getDocumentMeta('doc-missing');

      expect(result).toBeNull();
    });

    it('should return parsed metadata', async () => {
      mockRedis.hgetall.mockResolvedValue({
        documentId: 'doc-123',
        createdAt: '2024-01-01T00:00:00Z',
        lastModifiedAt: '2024-01-02T12:00:00Z',
        lastModifiedBy: 'user-1',
        version: '42',
      });

      const result = await store.getDocumentMeta('doc-123');

      expect(result).toEqual({
        documentId: 'doc-123',
        createdAt: '2024-01-01T00:00:00Z',
        lastModifiedAt: '2024-01-02T12:00:00Z',
        lastModifiedBy: 'user-1',
        version: 42,
      });
    });
  });

  describe('createSnapshot', () => {
    it('should create and store a snapshot', async () => {
      mockRedis.lpush.mockResolvedValue(undefined);
      mockRedis.llen.mockResolvedValue(1);
      mockRedis.expire.mockResolvedValue(undefined);

      const state = Buffer.from(new Uint8Array([10, 20, 30]));
      const snapshot = await store.createSnapshot(
        'doc-123',
        state,
        'user-1',
        'Version 1',
      );

      expect(snapshot.documentId).toBe('doc-123');
      expect(snapshot.createdBy).toBe('user-1');
      expect(snapshot.label).toBe('Version 1');
      expect(snapshot.id).toBeDefined();
      expect(snapshot.createdAt).toBeDefined();
      expect(snapshot.state).toBe(state.toString('base64'));
      expect(mockRedis.lpush).toHaveBeenCalledWith(
        'doc:snapshots:doc-123',
        expect.any(String),
      );
    });

    it('should trim snapshots when exceeding max', async () => {
      mockRedis.lpush.mockResolvedValue(undefined);
      mockRedis.llen.mockResolvedValue(55);
      mockRedis.ltrim.mockResolvedValue(undefined);
      mockRedis.expire.mockResolvedValue(undefined);

      const state = Buffer.from(new Uint8Array([1]));
      await store.createSnapshot('doc-123', state, 'user-1');

      expect(mockRedis.ltrim).toHaveBeenCalledWith('doc:snapshots:doc-123', 0, 49);
    });

    it('should not trim when under max snapshots', async () => {
      mockRedis.lpush.mockResolvedValue(undefined);
      mockRedis.llen.mockResolvedValue(10);
      mockRedis.expire.mockResolvedValue(undefined);

      const state = Buffer.from(new Uint8Array([1]));
      await store.createSnapshot('doc-123', state, 'user-1');

      expect(mockRedis.ltrim).not.toHaveBeenCalled();
    });

    it('should trim older snapshots beyond the per-document byte budget', async () => {
      const bounded = new DocumentStore(mockRedis, mockLogger, {
        maxSnapshots: 50,
        maxSnapshotBytes: 250,
      });
      mockRedis.lpush.mockResolvedValue(undefined);
      mockRedis.llen.mockResolvedValue(3);
      mockRedis.lrange.mockResolvedValue(['a', 'b', 'c'].map((c) => c.repeat(100)));
      mockRedis.expire.mockResolvedValue(undefined);

      await bounded.createSnapshot('doc-123', Buffer.from([1]), 'user-1');

      expect(mockRedis.ltrim).toHaveBeenCalledWith('doc:snapshots:doc-123', 0, 1);
    });

    it('should reject snapshots larger than the state size limit', async () => {
      const bounded = new DocumentStore(mockRedis, mockLogger, { maxStateBytes: 4 });

      await expect(
        bounded.createSnapshot('doc-123', Buffer.alloc(5), 'user-1'),
      ).rejects.toBeInstanceOf(DocumentTooLargeError);
      expect(mockRedis.lpush).not.toHaveBeenCalled();
    });
  });

  describe('state size limit', () => {
    it('should refuse to persist a document state over the limit', async () => {
      const bounded = new DocumentStore(mockRedis, mockLogger, { maxStateBytes: 4 });

      await expect(
        bounded.saveDocumentState('doc-123', Buffer.alloc(5)),
      ).rejects.toBeInstanceOf(DocumentTooLargeError);
      expect(mockRedis.set).not.toHaveBeenCalled();
    });
  });

  describe('getSnapshots', () => {
    it('should return parsed snapshots', async () => {
      const snapshots = [
        JSON.stringify({
          id: 'snap-1',
          documentId: 'doc-123',
          state: Buffer.from([1, 2]).toString('base64'),
          createdAt: '2024-01-01T00:00:00Z',
          createdBy: 'user-1',
          label: 'First',
        }),
        JSON.stringify({
          id: 'snap-2',
          documentId: 'doc-123',
          state: Buffer.from([3, 4]).toString('base64'),
          createdAt: '2024-01-02T00:00:00Z',
          createdBy: 'user-2',
        }),
      ];
      mockRedis.lrange.mockResolvedValue(snapshots);

      const result = await store.getSnapshots('doc-123', 10);

      expect(result).toHaveLength(2);
      expect(result[0].id).toBe('snap-1');
      expect(result[0].label).toBe('First');
      expect(result[1].id).toBe('snap-2');
      expect(mockRedis.lrange).toHaveBeenCalledWith('doc:snapshots:doc-123', 0, 9);
    });

    it('should return empty array when no snapshots exist', async () => {
      mockRedis.lrange.mockResolvedValue([]);

      const result = await store.getSnapshots('doc-none');

      expect(result).toEqual([]);
    });
  });

  describe('getSnapshotState', () => {
    it('should return state for a specific snapshot', async () => {
      const stateBytes = new Uint8Array([10, 20, 30]);
      const snapshot = {
        id: 'snap-target',
        documentId: 'doc-123',
        state: Buffer.from(stateBytes).toString('base64'),
        createdAt: '2024-01-01T00:00:00Z',
        createdBy: 'user-1',
      };
      mockRedis.lrange.mockResolvedValue([JSON.stringify(snapshot)]);

      const result = await store.getSnapshotState('doc-123', 'snap-target');

      expect(result).toBeInstanceOf(Uint8Array);
      expect(result).toEqual(stateBytes);
    });

    it('should return null for non-existent snapshot', async () => {
      mockRedis.lrange.mockResolvedValue([]);

      const result = await store.getSnapshotState('doc-123', 'snap-missing');

      expect(result).toBeNull();
    });
  });
});
