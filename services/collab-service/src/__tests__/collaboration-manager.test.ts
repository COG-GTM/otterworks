import type { Logger } from 'pino';
import type { Server as SocketIOServer, Socket } from 'socket.io';
import * as Y from 'yjs';
import {
  CollaborationManager,
  setupCollaborationHandlers,
} from '../handlers/collaboration';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';
import { MetricsCollector } from '../metrics';
import type { DocumentStore } from '../services/document-store';
import type { AuthenticatedSocket } from '../middleware/auth';

const loggerMock = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
};
const logger = loggerMock as unknown as Logger;

// Shared across every test: each MetricsCollector installs process-level default collectors
// (GC observer, event-loop monitor) that registry.clear() does not tear down.
const metrics = new MetricsCollector();

afterAll(() => {
  metrics.registry.clear();
});

interface FakeSocket {
  socket: Socket;
  id: string;
  emit: jest.Mock;
  roomEmit: jest.Mock;
  to: jest.Mock;
  join: jest.Mock;
  leave: jest.Mock;
  handlers: Map<string, (...args: never[]) => unknown>;
}

function createDocumentStoreMock() {
  return {
    getDocumentState: jest.fn().mockResolvedValue(null),
    saveDocumentState: jest.fn().mockResolvedValue(undefined),
    createSnapshot: jest.fn().mockResolvedValue({ id: 'snap-1', label: 'manual' }),
    getSnapshots: jest.fn().mockResolvedValue([]),
  };
}

type DocumentStoreMock = ReturnType<typeof createDocumentStoreMock>;

function encodeUpdate(text: string): string {
  const doc = new Y.Doc();
  doc.getText('content').insert(0, text);
  return Buffer.from(Y.encodeStateAsUpdate(doc)).toString('base64');
}

describe('CollaborationManager (faked sockets)', () => {
  let manager: CollaborationManager;
  let awareness: AwarenessService;
  let presenceHandler: PresenceHandler;
  let documentStore: DocumentStoreMock;
  let io: SocketIOServer;
  let ioRoomEmit: jest.Mock;
  let connectionHandler: (socket: Socket) => void;

  function createFakeSocket(id: string, userId?: string): FakeSocket {
    const roomEmit = jest.fn();
    const handlers = new Map<string, (...args: never[]) => unknown>();
    const socket = {
      id,
      emit: jest.fn(),
      to: jest.fn(() => ({ emit: roomEmit })),
      join: jest.fn().mockResolvedValue(undefined),
      leave: jest.fn(),
      on: jest.fn((event: string, handler: (...args: never[]) => unknown) => {
        handlers.set(event, handler);
      }),
    };
    if (userId) {
      (socket as unknown as AuthenticatedSocket).user = {
        userId,
        email: `${userId}@test.com`,
        displayName: userId.toUpperCase(),
        roles: ['user'],
      };
    }
    return {
      socket: socket as unknown as Socket,
      id,
      emit: socket.emit,
      roomEmit,
      to: socket.to,
      join: socket.join,
      leave: socket.leave,
      handlers,
    };
  }

  function connect(id: string, userId?: string): FakeSocket {
    const fake = createFakeSocket(id, userId);
    connectionHandler(fake.socket);
    return fake;
  }

  function fire(fake: FakeSocket, event: string, ...args: unknown[]): unknown {
    const handler = fake.handlers.get(event);
    if (!handler) throw new Error(`no handler registered for "${event}"`);
    return (handler as (...a: unknown[]) => unknown)(...args);
  }

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));

    ioRoomEmit = jest.fn();
    io = {
      on: jest.fn((event: string, handler: (socket: Socket) => void) => {
        if (event === 'connection') connectionHandler = handler;
      }),
      to: jest.fn(() => ({ emit: ioRoomEmit })),
      sockets: { sockets: new Map() },
    } as unknown as SocketIOServer;

    awareness = new AwarenessService(logger);
    presenceHandler = new PresenceHandler(awareness, logger);
    documentStore = createDocumentStoreMock();

    manager = new CollaborationManager({
      io,
      documentStore: documentStore as unknown as DocumentStore,
      awareness,
      presenceHandler,
      metrics,
      logger,
      persistIntervalMs: 30000,
      snapshotIntervalMs: 300000,
    });
    manager.start();
  });

  afterEach(async () => {
    await manager.stop();
    jest.useRealTimers();
  });

  describe('join-document', () => {
    it('joins the room, syncs state, registers awareness and acknowledges', async () => {
      const alice = connect('sock-a', 'user-a');
      const ack = jest.fn();

      await fire(alice, 'join-document', { documentId: 'doc-1' }, ack);

      expect(alice.join).toHaveBeenCalledWith('doc:doc-1');
      expect(alice.emit).toHaveBeenCalledWith(
        'sync-document',
        expect.objectContaining({ documentId: 'doc-1', state: expect.any(String) }),
      );
      expect(alice.roomEmit).toHaveBeenCalledWith(
        'user-joined',
        expect.objectContaining({ userId: 'user-a', socketId: 'sock-a' }),
      );
      expect(ack).toHaveBeenCalledWith({ success: true });
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(manager.getDocumentCount()).toBe(1);
    });

    it('works without an acknowledgement callback', async () => {
      const alice = connect('sock-a', 'user-a');

      await fire(alice, 'join-document', { documentId: 'doc-1' });

      expect(manager.getDocument('doc-1')).toBeDefined();
    });

    it('hydrates the document from persisted state', async () => {
      const seed = new Y.Doc();
      seed.getText('content').insert(0, 'persisted');
      documentStore.getDocumentState.mockResolvedValueOnce(
        Buffer.from(Y.encodeStateAsUpdate(seed)),
      );
      const alice = connect('sock-a', 'user-a');

      await fire(alice, 'join-document', { documentId: 'doc-1' });

      expect(manager.getDocument('doc-1')?.getText('content').toString()).toBe(
        'persisted',
      );
    });

    it('reuses one in-memory document for concurrent joins', async () => {
      let release: (value: Buffer | null) => void = () => {};
      documentStore.getDocumentState.mockReturnValueOnce(
        new Promise<Buffer | null>((resolve) => {
          release = resolve;
        }),
      );
      const alice = connect('sock-a', 'user-a');
      const bob = connect('sock-b', 'user-b');

      const joins = Promise.all([
        fire(alice, 'join-document', { documentId: 'doc-1' }),
        fire(bob, 'join-document', { documentId: 'doc-1' }),
      ]);
      release(null);
      await joins;

      expect(documentStore.getDocumentState).toHaveBeenCalledTimes(1);
      expect(manager.getDocumentCount()).toBe(1);
      expect(awareness.getDocumentUserCount('doc-1')).toBe(2);
    });

    it('leaves the previous document, notifying it, when a socket switches', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });

      await fire(alice, 'join-document', { documentId: 'doc-2' });

      expect(alice.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(alice.to).toHaveBeenCalledWith('doc:doc-1');
      expect(alice.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 'sock-a',
        userId: 'user-a',
      });
      expect(awareness.getUserDocument('sock-a')).toBe('doc-2');
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
    });

    it('reports a failed join to the client and leaves the room', async () => {
      documentStore.getDocumentState.mockRejectedValueOnce(new Error('redis down'));
      const alice = connect('sock-a', 'user-a');
      const ack = jest.fn();

      await fire(alice, 'join-document', { documentId: 'doc-1' }, ack);

      expect(ack).toHaveBeenCalledWith({
        success: false,
        error: 'Failed to join document',
      });
      expect(alice.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(manager.getDocument('doc-1')).toBeUndefined();
    });

    it('swallows a failed join with no acknowledgement callback', async () => {
      documentStore.getDocumentState.mockRejectedValueOnce(new Error('redis down'));
      const alice = connect('sock-a', 'user-a');

      await expect(
        fire(alice, 'join-document', { documentId: 'doc-1' }),
      ).resolves.toBeUndefined();
    });
  });

  describe('document-update', () => {
    it('applies a base64 CRDT update, broadcasts it and persists the full state', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      const update = encodeUpdate('hello');

      await fire(alice, 'document-update', { documentId: 'doc-1', update });

      expect(manager.getDocument('doc-1')?.getText('content').toString()).toBe('hello');
      expect(alice.roomEmit).toHaveBeenCalledWith('document-update', {
        documentId: 'doc-1',
        update,
      });
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'user-a',
      );
    });

    it('ignores updates for a document that is not loaded', async () => {
      const alice = connect('sock-a', 'user-a');

      await fire(alice, 'document-update', {
        documentId: 'doc-missing',
        update: encodeUpdate('hello'),
      });

      expect(alice.roomEmit).not.toHaveBeenCalled();
      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });

    it('reports an undecodable update back to the sender only', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      alice.roomEmit.mockClear();

      await fire(alice, 'document-update', {
        documentId: 'doc-1',
        update: 'bm90LWEteWpzLXVwZGF0ZQ==',
      });

      expect(alice.emit).toHaveBeenCalledWith('document-update-error', {
        documentId: 'doc-1',
        error: 'Failed to apply update',
      });
      expect(alice.roomEmit).not.toHaveBeenCalled();
    });

    it('broadcasts non-string (legacy JSON) payloads without CRDT decoding', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      const patch = { op: 'replace', value: 'x' };

      await fire(alice, 'document-update', { documentId: 'doc-1', update: patch });

      expect(alice.roomEmit).toHaveBeenCalledWith('document-update', {
        documentId: 'doc-1',
        update: patch,
      });
    });

    it('still broadcasts when persistence fails', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await fire(alice, 'document-update', {
        documentId: 'doc-1',
        update: encodeUpdate('hello'),
      });

      expect(alice.roomEmit).toHaveBeenCalledWith(
        'document-update',
        expect.objectContaining({ documentId: 'doc-1' }),
      );
      expect(loggerMock.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'document_persist_failed',
      );
    });
  });

  describe('cursor and typing indicators', () => {
    it('broadcasts a cursor update enriched with the sender identity', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      const cursor = { index: 42, length: 0 };

      fire(alice, 'cursor-update', { documentId: 'doc-1', cursor, selection: null });

      expect(alice.roomEmit).toHaveBeenCalledWith(
        'cursor-update',
        expect.objectContaining({
          socketId: 'sock-a',
          userId: 'user-a',
          cursor,
          selection: null,
        }),
      );
    });

    it('ignores cursor updates from a socket with no awareness entry', () => {
      const ghost = connect('sock-ghost', 'user-ghost');

      fire(ghost, 'cursor-update', {
        documentId: 'doc-1',
        cursor: { index: 1, length: 0 },
        selection: null,
      });

      expect(ghost.roomEmit).not.toHaveBeenCalled();
    });

    it('broadcasts typing state changes', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });

      fire(alice, 'typing-indicator', { documentId: 'doc-1', isTyping: true });

      expect(alice.roomEmit).toHaveBeenCalledWith('typing-indicator', {
        socketId: 'sock-a',
        userId: 'user-a',
        displayName: 'USER-A',
        isTyping: true,
      });
    });

    it('ignores typing indicators from a socket with no awareness entry', () => {
      const ghost = connect('sock-ghost', 'user-ghost');

      fire(ghost, 'typing-indicator', { documentId: 'doc-1', isTyping: true });

      expect(ghost.roomEmit).not.toHaveBeenCalled();
    });
  });

  describe('comment annotations', () => {
    it('stamps a new comment with its author and echoes it to the room and sender', () => {
      const alice = connect('sock-a', 'user-a');

      fire(alice, 'comment-add', {
        documentId: 'doc-1',
        comment: {
          id: 'c-1',
          threadId: 't-1',
          content: 'looks good',
          rangeStart: 0,
          rangeEnd: 5,
        },
      });

      const expected = {
        id: 'c-1',
        threadId: 't-1',
        content: 'looks good',
        documentId: 'doc-1',
        rangeStart: 0,
        rangeEnd: 5,
        author: { userId: 'user-a', displayName: 'USER-A' },
        createdAt: '2026-01-01T00:00:00.000Z',
      };
      expect(alice.roomEmit).toHaveBeenCalledWith('comment-added', expected);
      expect(alice.emit).toHaveBeenCalledWith('comment-added', expected);
    });

    it('broadcasts a comment edit with the editor and timestamp', () => {
      const alice = connect('sock-a', 'user-a');

      fire(alice, 'comment-update', {
        documentId: 'doc-1',
        commentId: 'c-1',
        content: 'edited',
      });

      expect(alice.roomEmit).toHaveBeenCalledWith('comment-updated', {
        commentId: 'c-1',
        content: 'edited',
        updatedBy: { userId: 'user-a', displayName: 'USER-A' },
        updatedAt: '2026-01-01T00:00:00.000Z',
      });
    });

    it('broadcasts a comment deletion, attributing anonymous sockets by id', () => {
      const anon = connect('sock-anon');

      fire(anon, 'comment-delete', { documentId: 'doc-1', commentId: 'c-1' });

      expect(anon.roomEmit).toHaveBeenCalledWith('comment-deleted', {
        commentId: 'c-1',
        deletedBy: 'anon-sock-anon',
      });
    });
  });

  describe('snapshots and history', () => {
    it('creates a snapshot and shares it with the room', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });

      await fire(alice, 'request-snapshot', { documentId: 'doc-1', label: 'v1' });

      expect(documentStore.createSnapshot).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'user-a',
        'v1',
      );
      expect(alice.emit).toHaveBeenCalledWith('snapshot-created', {
        id: 'snap-1',
        label: 'manual',
      });
      expect(alice.roomEmit).toHaveBeenCalledWith('snapshot-created', {
        id: 'snap-1',
        label: 'manual',
      });
    });

    it('rejects a snapshot request for a document that is not loaded', async () => {
      const alice = connect('sock-a', 'user-a');

      await fire(alice, 'request-snapshot', { documentId: 'doc-missing' });

      expect(documentStore.createSnapshot).not.toHaveBeenCalled();
      expect(alice.emit).toHaveBeenCalledWith('snapshot-error', {
        documentId: 'doc-missing',
        error: 'Document not found',
      });
    });

    it('reports snapshot storage failures to the requester', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      documentStore.createSnapshot.mockRejectedValueOnce(new Error('redis down'));

      await fire(alice, 'request-snapshot', { documentId: 'doc-1' });

      expect(alice.emit).toHaveBeenCalledWith('snapshot-error', {
        documentId: 'doc-1',
        error: 'Failed to create snapshot',
      });
    });

    it('returns history with an explicit limit and with the default limit', async () => {
      const alice = connect('sock-a', 'user-a');
      documentStore.getSnapshots.mockResolvedValue([{ id: 'snap-1' }]);

      await fire(alice, 'request-history', { documentId: 'doc-1', limit: 5 });
      await fire(alice, 'request-history', { documentId: 'doc-1' });

      expect(documentStore.getSnapshots).toHaveBeenNthCalledWith(1, 'doc-1', 5);
      expect(documentStore.getSnapshots).toHaveBeenNthCalledWith(2, 'doc-1', 20);
      expect(alice.emit).toHaveBeenCalledWith('document-history', {
        documentId: 'doc-1',
        snapshots: [{ id: 'snap-1' }],
      });
    });

    it('reports history lookup failures to the requester', async () => {
      const alice = connect('sock-a', 'user-a');
      documentStore.getSnapshots.mockRejectedValueOnce(new Error('redis down'));

      await fire(alice, 'request-history', { documentId: 'doc-1' });

      expect(alice.emit).toHaveBeenCalledWith('history-error', {
        documentId: 'doc-1',
        error: 'Failed to retrieve history',
      });
    });
  });

  describe('leaving and disconnecting', () => {
    it('removes the user, notifies the room and unloads the emptied document', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });

      fire(alice, 'leave-document', { documentId: 'doc-1' });
      await Promise.resolve();
      await Promise.resolve();

      expect(alice.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(alice.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 'sock-a',
        userId: 'user-a',
      });
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
      expect(manager.getDocument('doc-1')).toBeUndefined();
    });

    it('keeps the document loaded while other users remain', async () => {
      const alice = connect('sock-a', 'user-a');
      const bob = connect('sock-b', 'user-b');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      await fire(bob, 'join-document', { documentId: 'doc-1' });

      fire(alice, 'leave-document', { documentId: 'doc-1' });

      expect(manager.getDocument('doc-1')).toBeDefined();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });

    it('falls back to the client-provided document id for an untracked socket', () => {
      const ghost = connect('sock-ghost', 'user-ghost');

      fire(ghost, 'leave-document', { documentId: 'doc-1' });

      expect(ghost.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(ghost.roomEmit).not.toHaveBeenCalled();
    });

    it('cleans up awareness and the document on disconnect', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });

      fire(alice, 'disconnect', 'transport close');
      await Promise.resolve();
      await Promise.resolve();

      expect(alice.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 'sock-a',
        userId: 'user-a',
      });
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
      expect(manager.getDocument('doc-1')).toBeUndefined();
    });

    it('ignores a disconnect from a socket that never joined a document', () => {
      const ghost = connect('sock-ghost', 'user-ghost');

      fire(ghost, 'disconnect', 'transport close');

      expect(ghost.roomEmit).not.toHaveBeenCalled();
    });
  });

  describe('persistAndCleanupDocument', () => {
    it('is a no-op for a document that is not loaded', async () => {
      await manager.persistAndCleanupDocument('doc-missing');

      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });

    it('keeps the document in memory when persistence fails', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      awareness.removeUser('sock-a');
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await manager.persistAndCleanupDocument('doc-1');

      expect(manager.getDocument('doc-1')).toBeDefined();
      expect(loggerMock.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'document_persist_on_cleanup_failed',
      );
    });

    it('keeps the document when a user re-joins during persistence', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      awareness.removeUser('sock-a');
      documentStore.saveDocumentState.mockImplementationOnce(async () => {
        awareness.addUser('doc-1', 'sock-b', 'user-b', 'Bob', 'b@test.com');
      });

      await manager.persistAndCleanupDocument('doc-1');

      expect(manager.getDocument('doc-1')).toBeDefined();
    });

    it('ignores a concurrent cleanup for the same document', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      awareness.removeUser('sock-a');
      let release: () => void = () => {};
      documentStore.saveDocumentState.mockImplementationOnce(
        () =>
          new Promise<void>((resolve) => {
            release = resolve;
          }),
      );

      const first = manager.persistAndCleanupDocument('doc-1');
      await manager.persistAndCleanupDocument('doc-1');
      release();
      await first;

      expect(documentStore.saveDocumentState).toHaveBeenCalledTimes(1);
    });
  });

  describe('background loops', () => {
    it('persists every loaded document on the persistence interval', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      documentStore.saveDocumentState.mockClear();

      await jest.advanceTimersByTimeAsync(30000);

      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
    });

    it('logs but survives a failing periodic persistence', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await jest.advanceTimersByTimeAsync(30000);

      expect(loggerMock.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'periodic_persistence_failed',
      );
    });

    it('writes an automatic snapshot on the snapshot interval', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });

      await jest.advanceTimersByTimeAsync(300000);

      expect(documentStore.createSnapshot).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'system',
        'auto-snapshot',
      );
    });

    it('logs but survives a failing periodic snapshot', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      documentStore.createSnapshot.mockRejectedValueOnce(new Error('redis down'));

      await jest.advanceTimersByTimeAsync(300000);

      expect(loggerMock.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'periodic_snapshot_failed',
      );
    });
  });

  describe('stop', () => {
    it('flushes every loaded document before shutting down', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      documentStore.saveDocumentState.mockClear();

      await manager.stop();

      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
      expect(loggerMock.info).toHaveBeenCalledWith('collaboration_manager_stopped');
    });

    it('logs a failed shutdown flush without throwing', async () => {
      const alice = connect('sock-a', 'user-a');
      await fire(alice, 'join-document', { documentId: 'doc-1' });
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await expect(manager.stop()).resolves.toBeUndefined();
      expect(loggerMock.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'document_persist_on_shutdown_failed',
      );
    });
  });
});

describe('setupCollaborationHandlers', () => {
  it('builds a started manager wired to the connection event', async () => {
    const io = {
      on: jest.fn(),
      to: jest.fn(() => ({ emit: jest.fn() })),
      sockets: { sockets: new Map() },
    } as unknown as SocketIOServer;
    const awareness = new AwarenessService(logger);
    const documentStore = createDocumentStoreMock();

    const manager = setupCollaborationHandlers(
      io,
      documentStore as unknown as DocumentStore,
      awareness,
      new PresenceHandler(awareness, logger),
      metrics,
      logger,
    );

    expect(io.on).toHaveBeenCalledWith('connection', expect.any(Function));
    expect(manager.getDocumentCount()).toBe(0);

    await manager.stop();
    metrics.registry.clear();
  });
});
