import type { Server as SocketIOServer, Socket } from 'socket.io';
import * as Y from 'yjs';
import {
  CollaborationManager,
  setupCollaborationHandlers,
  type CollaborationDeps,
} from '../handlers/collaboration';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';
import { MetricsCollector } from '../metrics';
import type { DocumentStore } from '../services/document-store';

type Handler = (...args: unknown[]) => unknown;

function makeLogger() {
  return { info: jest.fn(), warn: jest.fn(), error: jest.fn(), debug: jest.fn() };
}

function makeStore() {
  return {
    getDocumentState: jest.fn().mockResolvedValue(null),
    saveDocumentState: jest.fn().mockResolvedValue(undefined),
    createSnapshot: jest.fn(),
    getSnapshots: jest.fn().mockResolvedValue([]),
  };
}

function makeIo() {
  let onConnection: ((socket: Socket) => void) | undefined;
  const roomEmit = jest.fn();
  const raw = {
    on: jest.fn((event: string, fn: (socket: Socket) => void) => {
      if (event === 'connection') onConnection = fn;
    }),
    to: jest.fn(() => ({ emit: roomEmit })),
  };
  return {
    io: raw as unknown as SocketIOServer,
    raw,
    roomEmit,
    connect: (socket: Socket) => onConnection?.(socket),
  };
}

function makeSocket(
  id: string,
  user?: { userId: string; displayName: string; email: string },
) {
  const handlers: Record<string, Handler> = {};
  const toEmit = jest.fn();
  const raw = {
    id,
    user: user ? { ...user, roles: [] } : undefined,
    on: jest.fn((event: string, fn: Handler) => {
      handlers[event] = fn;
    }),
    emit: jest.fn(),
    join: jest.fn().mockResolvedValue(undefined),
    leave: jest.fn(),
    to: jest.fn(() => ({ emit: toEmit })),
  };
  return { socket: raw as unknown as Socket, raw, handlers, toEmit };
}

function yUpdate(text: string): Uint8Array {
  const doc = new Y.Doc();
  doc.getText('content').insert(0, text);
  return Y.encodeStateAsUpdate(doc);
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

describe('CollaborationManager (unit)', () => {
  let logger: ReturnType<typeof makeLogger>;
  let store: ReturnType<typeof makeStore>;
  let ioCtl: ReturnType<typeof makeIo>;
  let awareness: AwarenessService;
  let presence: PresenceHandler;
  let metrics: MetricsCollector;
  let manager: CollaborationManager;
  let deps: CollaborationDeps;

  beforeEach(() => {
    logger = makeLogger();
    store = makeStore();
    ioCtl = makeIo();
    awareness = new AwarenessService(logger as never);
    presence = new PresenceHandler(awareness, logger as never);
    metrics = new MetricsCollector();
    deps = {
      io: ioCtl.io,
      documentStore: store as unknown as DocumentStore,
      awareness,
      presenceHandler: presence,
      metrics,
      logger: logger as never,
      persistIntervalMs: 1000,
      snapshotIntervalMs: 5000,
    };
    manager = new CollaborationManager(deps);
  });

  afterEach(async () => {
    await manager.stop();
    jest.useRealTimers();
  });

  async function metricValue(name: string, labels: Record<string, string> = {}) {
    const metric = await metrics.registry.getSingleMetric(name)?.get();
    const entry = metric?.values.find((v) =>
      Object.entries(labels).every(([k, val]) => v.labels[k] === val),
    );
    return entry?.value ?? 0;
  }

  function connect(
    id: string,
    user = { userId: `u-${id}`, displayName: id, email: `${id}@x` },
  ) {
    const s = makeSocket(id, user);
    ioCtl.connect(s.socket);
    return s;
  }

  async function join(s: ReturnType<typeof makeSocket>, documentId: string) {
    const ack = jest.fn();
    await s.handlers['join-document']({ documentId }, ack);
    return ack;
  }

  describe('start / connection', () => {
    it('registers socket handlers on connection and counts connections', async () => {
      manager.start();
      const s = connect('s1');
      expect(Object.keys(s.handlers).sort()).toEqual(
        [
          'comment-add',
          'comment-delete',
          'comment-update',
          'cursor-update',
          'disconnect',
          'document-update',
          'join-document',
          'leave-document',
          'request-history',
          'request-snapshot',
          'typing-indicator',
        ].sort(),
      );
      expect(await metricValue('collab_active_connections')).toBe(1);
      expect(logger.info).toHaveBeenCalledWith('collaboration_manager_started');
    });
  });

  describe('join-document', () => {
    beforeEach(() => manager.start());

    it('creates the doc, syncs state, notifies the room and acks', async () => {
      const s = connect('s1');
      const ack = await join(s, 'd1');

      expect(ack).toHaveBeenCalledWith({ success: true });
      expect(s.raw.join).toHaveBeenCalledWith('doc:d1');
      expect(manager.getDocument('d1')).toBeInstanceOf(Y.Doc);
      expect(manager.getDocumentCount()).toBe(1);
      expect(s.raw.emit).toHaveBeenCalledWith('sync-document', {
        documentId: 'd1',
        state: expect.any(String),
      });
      expect(s.toEmit).toHaveBeenCalledWith(
        'user-joined',
        expect.objectContaining({ userId: 'u-s1', displayName: 's1', socketId: 's1' }),
      );
      expect(ioCtl.roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'd1', count: 1 }),
      );
      expect(await metricValue('collab_active_rooms')).toBe(1);
      expect(await metricValue('collab_messages_total', { type: 'join-document' })).toBe(
        1,
      );
    });

    it('hydrates the doc from persisted state', async () => {
      store.getDocumentState.mockResolvedValue(yUpdate('hello'));
      const s = connect('s1');
      await join(s, 'd1');
      expect(manager.getDocument('d1')!.getText('content').toString()).toBe('hello');

      const sync = s.raw.emit.mock.calls.find((c) => c[0] === 'sync-document')![1];
      const replica = new Y.Doc();
      Y.applyUpdate(replica, new Uint8Array(Buffer.from(sync.state, 'base64')));
      expect(replica.getText('content').toString()).toBe('hello');
    });

    it('works without an ack callback', async () => {
      const s = connect('s1');
      await expect(
        s.handlers['join-document']({ documentId: 'd1' }),
      ).resolves.toBeUndefined();
      expect(manager.getDocument('d1')).toBeDefined();
    });

    it('uses an anonymous identity when the socket is unauthenticated', async () => {
      const s = makeSocket('anon1');
      ioCtl.connect(s.socket);
      await join(s, 'd1');
      expect(awareness.getDocumentUsers('d1')[0]).toMatchObject({
        userId: 'anon-anon1',
        displayName: 'Anonymous',
      });
    });

    it('loads the doc once for concurrent joins', async () => {
      let resolveState!: (v: null) => void;
      store.getDocumentState.mockReturnValue(
        new Promise((resolve) => {
          resolveState = resolve;
        }),
      );
      const a = connect('a');
      const b = connect('b');
      const p1 = join(a, 'd1');
      const p2 = join(b, 'd1');
      await flush();
      resolveState(null);
      const [ack1, ack2] = await Promise.all([p1, p2]);

      expect(store.getDocumentState).toHaveBeenCalledTimes(1);
      expect(ack1).toHaveBeenCalledWith({ success: true });
      expect(ack2).toHaveBeenCalledWith({ success: true });
      expect(manager.getDocumentCount()).toBe(1);
      expect(await metricValue('collab_active_rooms')).toBe(1);
    });

    it('re-joining the same document does not trigger a switch', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      await join(s, 'd1');
      expect(s.raw.leave).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('d1')).toBe(1);
    });

    it('switching documents leaves the old room and cleans up the empty doc', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      s.toEmit.mockClear();

      await join(s, 'd2');
      await flush();

      expect(s.raw.leave).toHaveBeenCalledWith('doc:d1');
      expect(s.raw.to).toHaveBeenCalledWith('doc:d1');
      expect(s.toEmit).toHaveBeenCalledWith('user-left', {
        socketId: 's1',
        userId: 'u-s1',
      });
      expect(store.saveDocumentState).toHaveBeenCalledWith('d1', expect.any(Buffer));
      expect(manager.getDocument('d1')).toBeUndefined();
      expect(manager.getDocument('d2')).toBeDefined();
      expect(awareness.getUserDocument('s1')).toBe('d2');
      expect(logger.info).toHaveBeenCalledWith(
        expect.objectContaining({ oldDocumentId: 'd1', newDocumentId: 'd2' }),
        'user_switched_documents',
      );
    });

    it('switching documents keeps the old doc while others remain', async () => {
      const a = connect('a');
      const b = connect('b');
      await join(a, 'd1');
      await join(b, 'd1');
      await join(a, 'd2');
      await flush();
      expect(manager.getDocument('d1')).toBeDefined();
      expect(store.saveDocumentState).not.toHaveBeenCalled();
    });

    it('fails gracefully when loading state fails', async () => {
      store.getDocumentState.mockRejectedValue(new Error('redis down'));
      const s = connect('s1');
      const ack = await join(s, 'd1');

      expect(ack).toHaveBeenCalledWith({
        success: false,
        error: 'Failed to join document',
      });
      expect(s.raw.leave).toHaveBeenCalledWith('doc:d1');
      expect(manager.getDocument('d1')).toBeUndefined();
      expect(
        await metricValue('collab_connection_errors_total', { reason: 'join_failed' }),
      ).toBe(1);

      store.getDocumentState.mockResolvedValue(null);
      const retryAck = await join(s, 'd1');
      expect(retryAck).toHaveBeenCalledWith({ success: true });
    });

    it('fails gracefully without an ack callback', async () => {
      store.getDocumentState.mockRejectedValue(new Error('redis down'));
      const s = connect('s1');
      await s.handlers['join-document']({ documentId: 'd1' });
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'd1' }),
        'join_document_failed',
      );
    });
  });

  describe('leave-document', () => {
    beforeEach(() => manager.start());

    it('removes the user, notifies the room and evicts the empty doc', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      s.toEmit.mockClear();

      s.handlers['leave-document']({ documentId: 'd1' });
      await flush();

      expect(s.raw.leave).toHaveBeenCalledWith('doc:d1');
      expect(s.toEmit).toHaveBeenCalledWith('user-left', {
        socketId: 's1',
        userId: 'u-s1',
      });
      expect(manager.getDocument('d1')).toBeUndefined();
      expect(await metricValue('collab_messages_total', { type: 'leave-document' })).toBe(
        1,
      );
      expect(await metricValue('collab_active_rooms')).toBe(0);
    });

    it('uses the tracked document rather than the client-supplied id', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      s.handlers['leave-document']({ documentId: 'spoofed' });
      expect(s.raw.leave).toHaveBeenCalledWith('doc:d1');
    });

    it('falls back to the client-supplied id when not tracked', async () => {
      const s = connect('s1');
      s.handlers['leave-document']({ documentId: 'd9' });
      await flush();
      expect(s.raw.leave).toHaveBeenCalledWith('doc:d9');
      expect(s.toEmit).not.toHaveBeenCalled();
      expect(store.saveDocumentState).not.toHaveBeenCalled();
    });

    it('keeps the doc in memory while other users remain', async () => {
      const a = connect('a');
      const b = connect('b');
      await join(a, 'd1');
      await join(b, 'd1');
      a.handlers['leave-document']({ documentId: 'd1' });
      await flush();
      expect(manager.getDocument('d1')).toBeDefined();
      expect(store.saveDocumentState).not.toHaveBeenCalled();
    });
  });

  describe('document-update', () => {
    beforeEach(() => manager.start());

    it('ignores updates for documents not loaded in memory', async () => {
      const s = connect('s1');
      await s.handlers['document-update']({ documentId: 'nope', update: 'AAA=' });
      expect(logger.warn).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'nope' }),
        'document_update_for_unknown_doc',
      );
      expect(s.toEmit).not.toHaveBeenCalled();
    });

    it('applies a base64 Yjs update, broadcasts it and persists', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      s.toEmit.mockClear();
      const update = Buffer.from(yUpdate('abc')).toString('base64');

      await s.handlers['document-update']({ documentId: 'd1', update });

      expect(manager.getDocument('d1')!.getText('content').toString()).toBe('abc');
      expect(s.toEmit).toHaveBeenCalledWith('document-update', {
        documentId: 'd1',
        update,
      });
      expect(store.saveDocumentState).toHaveBeenCalledWith(
        'd1',
        expect.any(Buffer),
        'u-s1',
      );
      expect(await metricValue('collab_document_updates_total')).toBe(1);
      expect(
        await metricValue('collab_persistence_operations_total', {
          operation: 'save_state',
          status: 'success',
        }),
      ).toBe(1);
    });

    it('refreshes the editor activity timestamp', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      const spy = jest.spyOn(awareness, 'refreshActivity');
      await s.handlers['document-update']({
        documentId: 'd1',
        update: Buffer.from(yUpdate('x')).toString('base64'),
      });
      expect(spy).toHaveBeenCalledWith('s1');
    });

    it('rejects a malformed update without broadcasting', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      s.toEmit.mockClear();

      await s.handlers['document-update']({
        documentId: 'd1',
        update: Buffer.from([255, 255, 255]).toString('base64'),
      });

      expect(s.raw.emit).toHaveBeenCalledWith('document-update-error', {
        documentId: 'd1',
        error: 'Failed to apply update',
      });
      expect(s.toEmit).not.toHaveBeenCalled();
      expect(store.saveDocumentState).not.toHaveBeenCalled();
    });

    it('relays non-string payloads to the room', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      s.toEmit.mockClear();
      const patch = { ops: [{ insert: 'hi' }] };

      await s.handlers['document-update']({ documentId: 'd1', update: patch });

      expect(s.toEmit).toHaveBeenCalledWith('document-update', {
        documentId: 'd1',
        update: patch,
      });
    });

    it('records a persistence error but still broadcasts', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      s.toEmit.mockClear();
      store.saveDocumentState.mockRejectedValueOnce(new Error('write failed'));

      await s.handlers['document-update']({
        documentId: 'd1',
        update: Buffer.from(yUpdate('q')).toString('base64'),
      });

      expect(s.toEmit).toHaveBeenCalledWith('document-update', expect.anything());
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'd1' }),
        'document_persist_failed',
      );
      expect(
        await metricValue('collab_persistence_operations_total', {
          operation: 'save_state',
          status: 'error',
        }),
      ).toBe(1);
    });
  });

  describe('cursor-update and typing-indicator', () => {
    beforeEach(() => manager.start());

    it('broadcasts cursor updates for tracked users', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      s.toEmit.mockClear();
      const cursor = { index: 3, length: 0 };
      const selection = { index: 1, length: 2 };

      s.handlers['cursor-update']({ documentId: 'd1', cursor, selection });

      expect(s.toEmit).toHaveBeenCalledWith('cursor-update', {
        socketId: 's1',
        userId: 'u-s1',
        displayName: 's1',
        color: expect.any(String),
        cursor,
        selection,
      });
      expect(await metricValue('collab_presence_updates_total')).toBe(1);
    });

    it('ignores cursor updates from sockets not in a document', async () => {
      const s = connect('s1');
      s.handlers['cursor-update']({ documentId: 'd1', cursor: null, selection: null });
      expect(s.toEmit).not.toHaveBeenCalled();
      expect(await metricValue('collab_presence_updates_total')).toBe(0);
    });

    it('broadcasts typing indicators for tracked users', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      s.toEmit.mockClear();

      s.handlers['typing-indicator']({ documentId: 'd1', isTyping: true });

      expect(s.raw.to).toHaveBeenCalledWith('doc:d1');
      expect(s.toEmit).toHaveBeenCalledWith('typing-indicator', {
        socketId: 's1',
        userId: 'u-s1',
        displayName: 's1',
        isTyping: true,
      });
      expect(awareness.getDocumentUsers('d1')[0].isTyping).toBe(true);
    });

    it('ignores typing indicators from sockets not in a document', () => {
      const s = connect('s1');
      s.handlers['typing-indicator']({ documentId: 'd1', isTyping: true });
      expect(s.toEmit).not.toHaveBeenCalled();
    });
  });

  describe('comments', () => {
    beforeEach(() => manager.start());

    it('comment-add stamps author/createdAt and emits to room and sender', async () => {
      const s = connect('s1');
      const comment = {
        id: 'c1',
        documentId: 'ignored',
        threadId: 't1',
        content: 'Nice',
        rangeStart: 0,
        rangeEnd: 4,
      };

      s.handlers['comment-add']({ documentId: 'd1', comment });

      const expected = {
        ...comment,
        documentId: 'd1',
        author: { userId: 'u-s1', displayName: 's1' },
        createdAt: expect.any(String),
      };
      expect(s.raw.to).toHaveBeenCalledWith('doc:d1');
      expect(s.toEmit).toHaveBeenCalledWith('comment-added', expected);
      expect(s.raw.emit).toHaveBeenCalledWith('comment-added', expected);
      expect(
        await metricValue('collab_comment_annotations_total', { action: 'add' }),
      ).toBe(1);
      expect(await metricValue('collab_messages_total', { type: 'comment-add' })).toBe(1);
    });

    it('comment-update broadcasts the edit with the editor identity', async () => {
      const s = connect('s1');
      s.handlers['comment-update']({
        documentId: 'd1',
        commentId: 'c1',
        content: 'Edited',
      });
      expect(s.toEmit).toHaveBeenCalledWith('comment-updated', {
        commentId: 'c1',
        content: 'Edited',
        updatedBy: { userId: 'u-s1', displayName: 's1' },
        updatedAt: expect.any(String),
      });
      expect(
        await metricValue('collab_comment_annotations_total', { action: 'update' }),
      ).toBe(1);
    });

    it('comment-delete broadcasts the deletion', async () => {
      const s = connect('s1');
      s.handlers['comment-delete']({ documentId: 'd1', commentId: 'c1' });
      expect(s.toEmit).toHaveBeenCalledWith('comment-deleted', {
        commentId: 'c1',
        deletedBy: 'u-s1',
      });
      expect(
        await metricValue('collab_comment_annotations_total', { action: 'delete' }),
      ).toBe(1);
    });
  });

  describe('snapshots and history', () => {
    beforeEach(() => manager.start());

    it('request-snapshot errors when the doc is not loaded', async () => {
      const s = connect('s1');
      await s.handlers['request-snapshot']({ documentId: 'd1' });
      expect(s.raw.emit).toHaveBeenCalledWith('snapshot-error', {
        documentId: 'd1',
        error: 'Document not found',
      });
      expect(store.createSnapshot).not.toHaveBeenCalled();
    });

    it('request-snapshot creates a snapshot and notifies sender and room', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      s.toEmit.mockClear();
      const snapshot = { id: 'snap1', documentId: 'd1' };
      store.createSnapshot.mockResolvedValue(snapshot);

      await s.handlers['request-snapshot']({ documentId: 'd1', label: 'v1' });

      expect(store.createSnapshot).toHaveBeenCalledWith(
        'd1',
        expect.any(Buffer),
        'u-s1',
        'v1',
      );
      expect(s.raw.emit).toHaveBeenCalledWith('snapshot-created', snapshot);
      expect(s.toEmit).toHaveBeenCalledWith('snapshot-created', snapshot);
    });

    it('request-snapshot reports store failures', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      store.createSnapshot.mockRejectedValue(new Error('nope'));
      await s.handlers['request-snapshot']({ documentId: 'd1' });
      expect(s.raw.emit).toHaveBeenCalledWith('snapshot-error', {
        documentId: 'd1',
        error: 'Failed to create snapshot',
      });
    });

    it('request-history defaults to 20 snapshots', async () => {
      const s = connect('s1');
      const snapshots = [{ id: 'a' }];
      store.getSnapshots.mockResolvedValue(snapshots);
      await s.handlers['request-history']({ documentId: 'd1' });
      expect(store.getSnapshots).toHaveBeenCalledWith('d1', 20);
      expect(s.raw.emit).toHaveBeenCalledWith('document-history', {
        documentId: 'd1',
        snapshots,
      });
    });

    it('request-history honours an explicit limit', async () => {
      const s = connect('s1');
      await s.handlers['request-history']({ documentId: 'd1', limit: 5 });
      expect(store.getSnapshots).toHaveBeenCalledWith('d1', 5);
    });

    it('request-history reports store failures', async () => {
      const s = connect('s1');
      store.getSnapshots.mockRejectedValue(new Error('nope'));
      await s.handlers['request-history']({ documentId: 'd1' });
      expect(s.raw.emit).toHaveBeenCalledWith('history-error', {
        documentId: 'd1',
        error: 'Failed to retrieve history',
      });
    });
  });

  describe('disconnect', () => {
    beforeEach(() => manager.start());

    it('notifies the room and evicts the doc when the last user leaves', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      s.toEmit.mockClear();

      s.handlers['disconnect']('transport close');
      await flush();

      expect(s.toEmit).toHaveBeenCalledWith('user-left', {
        socketId: 's1',
        userId: 'u-s1',
      });
      expect(store.saveDocumentState).toHaveBeenCalledWith('d1', expect.any(Buffer));
      expect(manager.getDocument('d1')).toBeUndefined();
      expect(await metricValue('collab_active_connections')).toBe(0);
    });

    it('keeps the doc while other users remain', async () => {
      const a = connect('a');
      const b = connect('b');
      await join(a, 'd1');
      await join(b, 'd1');
      a.handlers['disconnect']('client namespace disconnect');
      await flush();
      expect(manager.getDocument('d1')).toBeDefined();
    });

    it('handles sockets that never joined a document', async () => {
      const s = connect('s1');
      s.handlers['disconnect']('ping timeout');
      expect(s.toEmit).not.toHaveBeenCalled();
      expect(logger.info).toHaveBeenCalledWith(
        { socketId: 's1', reason: 'ping timeout' },
        'client_disconnected',
      );
    });
  });

  describe('persistAndCleanupDocument', () => {
    beforeEach(() => manager.start());

    it('is a no-op for unknown documents', async () => {
      await manager.persistAndCleanupDocument('nope');
      expect(store.saveDocumentState).not.toHaveBeenCalled();
    });

    it('ignores concurrent cleanup calls for the same document', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      awareness.removeUser('s1');
      await Promise.all([
        manager.persistAndCleanupDocument('d1'),
        manager.persistAndCleanupDocument('d1'),
      ]);
      expect(store.saveDocumentState).toHaveBeenCalledTimes(1);
      expect(manager.getDocument('d1')).toBeUndefined();
    });

    it('keeps the doc in memory when persistence fails', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      awareness.removeUser('s1');
      store.saveDocumentState.mockRejectedValueOnce(new Error('write failed'));

      await manager.persistAndCleanupDocument('d1');

      expect(manager.getDocument('d1')).toBeDefined();
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'd1' }),
        'document_persist_on_cleanup_failed',
      );
      await manager.persistAndCleanupDocument('d1');
      expect(manager.getDocument('d1')).toBeUndefined();
    });

    it('keeps the doc when a user re-joins during persistence', async () => {
      const s = connect('s1');
      await join(s, 'd1');
      awareness.removeUser('s1');
      store.saveDocumentState.mockImplementationOnce(async () => {
        awareness.addUser('d1', 's2', 'u2', 'B', 'b@x');
      });

      await manager.persistAndCleanupDocument('d1');
      expect(manager.getDocument('d1')).toBeDefined();
    });
  });

  describe('stop', () => {
    it('flushes in-memory documents and logs failures per document', async () => {
      manager.start();
      const a = connect('a');
      const b = connect('b');
      await join(a, 'd1');
      await join(b, 'd2');
      store.saveDocumentState
        .mockRejectedValueOnce(new Error('write failed'))
        .mockResolvedValueOnce(undefined);

      await manager.stop();

      expect(store.saveDocumentState).toHaveBeenCalledTimes(2);
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'd1' }),
        'document_persist_on_shutdown_failed',
      );
      expect(logger.info).toHaveBeenCalledWith(
        { documentId: 'd2' },
        'document_persisted_on_shutdown',
      );
      expect(logger.info).toHaveBeenCalledWith('collaboration_manager_stopped');
    });

    it('can be called before start', async () => {
      await expect(manager.stop()).resolves.toBeUndefined();
    });
  });

  describe('background loops', () => {
    beforeEach(() => {
      jest.useFakeTimers();
      manager.start();
    });

    it('periodically persists every in-memory document', async () => {
      const a = connect('a');
      const b = connect('b');
      await join(a, 'd1');
      await join(b, 'd2');
      store.saveDocumentState.mockRejectedValueOnce(new Error('write failed'));

      await jest.advanceTimersByTimeAsync(1000);

      expect(store.saveDocumentState).toHaveBeenCalledTimes(2);
      expect(
        await metricValue('collab_persistence_operations_total', {
          operation: 'periodic_save',
          status: 'error',
        }),
      ).toBe(1);
      expect(
        await metricValue('collab_persistence_operations_total', {
          operation: 'periodic_save',
          status: 'success',
        }),
      ).toBe(1);
    });

    it('periodically snapshots every in-memory document', async () => {
      const a = connect('a');
      const b = connect('b');
      await join(a, 'd1');
      await join(b, 'd2');
      store.createSnapshot
        .mockRejectedValueOnce(new Error('snap failed'))
        .mockResolvedValueOnce({ id: 'x' });

      await jest.advanceTimersByTimeAsync(5000);

      expect(store.createSnapshot).toHaveBeenCalledWith(
        expect.any(String),
        expect.any(Buffer),
        'system',
        'auto-snapshot',
      );
      expect(store.createSnapshot).toHaveBeenCalledTimes(2);
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'd1' }),
        'periodic_snapshot_failed',
      );
    });

    it('stop() clears the loops', async () => {
      const a = connect('a');
      await join(a, 'd1');
      await manager.stop();
      store.saveDocumentState.mockClear();
      await jest.advanceTimersByTimeAsync(10000);
      expect(store.saveDocumentState).not.toHaveBeenCalled();
      expect(store.createSnapshot).not.toHaveBeenCalled();
    });
  });
});

describe('setupCollaborationHandlers', () => {
  it('builds and starts a manager with default intervals', async () => {
    jest.useFakeTimers();
    const ioCtl = makeIo();
    const logger = makeLogger();
    const store = makeStore();
    const awareness = new AwarenessService(logger as never);
    const manager = setupCollaborationHandlers(
      ioCtl.io,
      store as unknown as DocumentStore,
      awareness,
      new PresenceHandler(awareness, logger as never),
      new MetricsCollector(),
      logger as never,
    );

    expect(manager).toBeInstanceOf(CollaborationManager);
    expect(ioCtl.raw.on).toHaveBeenCalledWith('connection', expect.any(Function));

    const s = makeSocket('s1', { userId: 'u1', displayName: 'U', email: 'u@x' });
    ioCtl.connect(s.socket);
    await s.handlers['join-document']({ documentId: 'd1' }, jest.fn());

    await jest.advanceTimersByTimeAsync(29999);
    expect(store.saveDocumentState).not.toHaveBeenCalled();
    await jest.advanceTimersByTimeAsync(1);
    expect(store.saveDocumentState).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(300000 - 30000);
    expect(store.createSnapshot).toHaveBeenCalledTimes(1);

    await manager.stop();
    jest.useRealTimers();
  });
});
