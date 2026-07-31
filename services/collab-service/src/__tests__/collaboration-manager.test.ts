import type { Logger } from 'pino';
import type { Server as SocketIOServer, Socket } from 'socket.io';
import * as Y from 'yjs';
import {
  CollaborationManager,
  setupCollaborationHandlers,
  type CollaborationDeps,
} from '../handlers/collaboration';
import { PresenceHandler } from '../handlers/presence';
import { MetricsCollector } from '../metrics';
import type { AuthenticatedSocket } from '../middleware/auth';
import { AwarenessService } from '../services/awareness';
import type { DocumentSnapshot, DocumentStore } from '../services/document-store';

type EventHandler = (...args: unknown[]) => unknown;

interface FakeSocket {
  socket: Socket;
  id: string;
  emit: jest.Mock;
  join: jest.Mock;
  leave: jest.Mock;
  to: jest.Mock;
  roomEmit: jest.Mock;
  fire: (event: string, ...args: unknown[]) => Promise<unknown>;
}

function createFakeSocket(id: string, userId?: string): FakeSocket {
  const handlers = new Map<string, EventHandler>();
  const roomEmit = jest.fn();
  const raw = {
    id,
    emit: jest.fn(),
    join: jest.fn().mockResolvedValue(undefined),
    leave: jest.fn(),
    to: jest.fn(() => ({ emit: roomEmit })),
    on: jest.fn((event: string, handler: EventHandler) => {
      handlers.set(event, handler);
    }),
  };

  if (userId) {
    (raw as unknown as AuthenticatedSocket).user = {
      userId,
      email: `${userId}@test.com`,
      displayName: userId.toUpperCase(),
      roles: ['user'],
    };
  }

  return {
    socket: raw as unknown as Socket,
    id,
    emit: raw.emit,
    join: raw.join,
    leave: raw.leave,
    to: raw.to,
    roomEmit,
    fire: async (event, ...args) => {
      const handler = handlers.get(event);
      if (!handler) throw new Error(`no handler registered for "${event}"`);
      return handler(...args);
    },
  };
}

interface FakeIo {
  server: SocketIOServer;
  emit: jest.Mock;
  to: jest.Mock;
  connect: (socket: FakeSocket) => void;
}

function createFakeIo(): FakeIo {
  const emit = jest.fn();
  const to = jest.fn(() => ({ emit }));
  let onConnection: ((socket: Socket) => void) | null = null;
  const server = {
    to,
    on: jest.fn((event: string, handler: (socket: Socket) => void) => {
      if (event === 'connection') onConnection = handler;
    }),
  } as unknown as SocketIOServer;

  return {
    server,
    emit,
    to,
    connect: (socket) => {
      if (!onConnection) throw new Error('manager did not subscribe to "connection"');
      onConnection(socket.socket);
    },
  };
}

function createLogger(): Logger {
  return {
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
    debug: jest.fn(),
    fatal: jest.fn(),
    trace: jest.fn(),
  } as unknown as Logger;
}

function createDocumentStore(): jest.Mocked<DocumentStore> {
  return {
    getDocumentState: jest.fn().mockResolvedValue(null),
    saveDocumentState: jest.fn().mockResolvedValue(undefined),
    deleteDocumentState: jest.fn().mockResolvedValue(undefined),
    getDocumentMeta: jest.fn().mockResolvedValue(null),
    createSnapshot: jest.fn(),
    getSnapshots: jest.fn().mockResolvedValue([]),
    getSnapshotState: jest.fn().mockResolvedValue(null),
  } as unknown as jest.Mocked<DocumentStore>;
}

function snapshot(overrides: Partial<DocumentSnapshot> = {}): DocumentSnapshot {
  return {
    id: 'snap-1',
    documentId: 'doc-1',
    state: 'AAA=',
    createdAt: '2026-01-01T00:00:00.000Z',
    createdBy: 'user-a',
    ...overrides,
  };
}

function encodedUpdate(text: string): string {
  const doc = new Y.Doc();
  doc.getText('content').insert(0, text);
  return Buffer.from(Y.encodeStateAsUpdate(doc)).toString('base64');
}

describe('CollaborationManager', () => {
  let io: FakeIo;
  let logger: Logger;
  let metrics: MetricsCollector;
  let awareness: AwarenessService;
  let presenceHandler: PresenceHandler;
  let documentStore: jest.Mocked<DocumentStore>;
  let manager: CollaborationManager;
  let deps: CollaborationDeps;

  function build(overrides: Partial<CollaborationDeps> = {}): CollaborationManager {
    deps = {
      io: io.server,
      documentStore,
      awareness,
      presenceHandler,
      metrics,
      logger,
      persistIntervalMs: 600000,
      snapshotIntervalMs: 900000,
      ...overrides,
    };
    return new CollaborationManager(deps);
  }

  async function connectAndJoin(
    socket: FakeSocket,
    documentId: string,
  ): Promise<{ success: boolean; error?: string }> {
    io.connect(socket);
    let ackResponse: { success: boolean; error?: string } = { success: false };
    await socket.fire(
      'join-document',
      { documentId },
      (response: { success: boolean; error?: string }) => {
        ackResponse = response;
      },
    );
    return ackResponse;
  }

  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    io = createFakeIo();
    logger = createLogger();
    metrics = new MetricsCollector();
    awareness = new AwarenessService(logger);
    presenceHandler = new PresenceHandler(awareness, logger);
    documentStore = createDocumentStore();
    documentStore.createSnapshot.mockResolvedValue(snapshot());
    manager = build();
    manager.start();
  });

  afterEach(async () => {
    await manager.stop();
    metrics.registry.clear();
    jest.useRealTimers();
    jest.clearAllMocks();
  });

  describe('start', () => {
    it('subscribes to new connections and counts them', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');

      io.connect(socket);

      const gauge = await metrics.activeConnections.get();
      expect(gauge.values[0].value).toBe(1);
      expect(logger.info).toHaveBeenCalledWith(
        { socketId: 'sock-a' },
        'client_connected',
      );
    });
  });

  describe('join-document', () => {
    it('joins the room, syncs state and announces the user', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');

      const ack = await connectAndJoin(socket, 'doc-1');

      expect(ack).toEqual({ success: true });
      expect(socket.join).toHaveBeenCalledWith('doc:doc-1');
      expect(socket.emit).toHaveBeenCalledWith('sync-document', {
        documentId: 'doc-1',
        state: expect.any(String),
      });
      expect(socket.roomEmit).toHaveBeenCalledWith('user-joined', {
        userId: 'user-a',
        displayName: 'USER-A',
        color: expect.any(String),
        socketId: 'sock-a',
      });
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(manager.getDocumentCount()).toBe(1);
      expect(manager.getDocument('doc-1')).toBeInstanceOf(Y.Doc);
    });

    it('hydrates the in-memory document from the persisted state', async () => {
      const persisted = new Y.Doc();
      persisted.getText('content').insert(0, 'restored');
      documentStore.getDocumentState.mockResolvedValueOnce(
        Y.encodeStateAsUpdate(persisted),
      );
      const socket = createFakeSocket('sock-a', 'user-a');

      await connectAndJoin(socket, 'doc-1');

      expect(manager.getDocument('doc-1')?.getText('content').toString()).toBe(
        'restored',
      );
    });

    it('works without an acknowledgement callback', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      io.connect(socket);

      await socket.fire('join-document', { documentId: 'doc-1' });

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });

    it('reuses a single initialisation for concurrent joins of the same document', async () => {
      const first = createFakeSocket('sock-a', 'user-a');
      const second = createFakeSocket('sock-b', 'user-b');
      io.connect(first);
      io.connect(second);

      await Promise.all([
        first.fire('join-document', { documentId: 'doc-1' }),
        second.fire('join-document', { documentId: 'doc-1' }),
      ]);

      expect(documentStore.getDocumentState).toHaveBeenCalledTimes(1);
      expect(manager.getDocumentCount()).toBe(1);
      expect(awareness.getDocumentUserCount('doc-1')).toBe(2);
    });

    it('leaves the previous document, persists it and tells the old room', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-old');
      socket.leave.mockClear();
      socket.roomEmit.mockClear();

      await socket.fire('join-document', { documentId: 'doc-new' }, () => {});

      expect(socket.leave).toHaveBeenCalledWith('doc:doc-old');
      expect(socket.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 'sock-a',
        userId: 'user-a',
      });
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-old',
        expect.any(Buffer),
      );
      expect(awareness.getUserDocument('sock-a')).toBe('doc-new');
      expect(manager.getDocument('doc-old')).toBeUndefined();
    });

    it('acknowledges a failure and leaves the room when loading state throws', async () => {
      documentStore.getDocumentState.mockRejectedValueOnce(new Error('redis down'));
      const socket = createFakeSocket('sock-a', 'user-a');

      const ack = await connectAndJoin(socket, 'doc-1');

      expect(ack).toEqual({ success: false, error: 'Failed to join document' });
      expect(socket.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(manager.getDocumentCount()).toBe(0);
      const errors = await metrics.connectionErrors.get();
      expect(errors.values[0]).toMatchObject({
        labels: { reason: 'join_failed' },
        value: 1,
      });
    });

    it('reports a join failure through the ack even without one registered', async () => {
      documentStore.getDocumentState.mockRejectedValueOnce(new Error('redis down'));
      const socket = createFakeSocket('sock-a', 'user-a');
      io.connect(socket);

      await expect(
        socket.fire('join-document', { documentId: 'doc-1' }),
      ).resolves.toBeUndefined();
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'join_document_failed',
      );
    });
  });

  describe('document-update', () => {
    it('ignores updates for a document that is not loaded', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      io.connect(socket);

      await socket.fire('document-update', {
        documentId: 'doc-unknown',
        update: encodedUpdate('hi'),
      });

      expect(socket.roomEmit).not.toHaveBeenCalled();
      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
      expect(logger.warn).toHaveBeenCalledWith(
        { documentId: 'doc-unknown', socketId: 'sock-a' },
        'document_update_for_unknown_doc',
      );
    });

    it('applies a base64 CRDT update, broadcasts it and persists the full state', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      documentStore.saveDocumentState.mockClear();
      const update = encodedUpdate('hello');

      await socket.fire('document-update', { documentId: 'doc-1', update });

      expect(manager.getDocument('doc-1')?.getText('content').toString()).toBe('hello');
      expect(socket.roomEmit).toHaveBeenCalledWith('document-update', {
        documentId: 'doc-1',
        update,
      });
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'user-a',
      );
      const applied = await metrics.documentUpdatesTotal.get();
      expect(applied.values[0].value).toBe(1);
    });

    it('rejects an update that is not a valid CRDT payload', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      socket.emit.mockClear();
      documentStore.saveDocumentState.mockClear();

      await socket.fire('document-update', {
        documentId: 'doc-1',
        update: Buffer.from([255, 255, 255]).toString('base64'),
      });

      expect(socket.emit).toHaveBeenCalledWith('document-update-error', {
        documentId: 'doc-1',
        error: 'Failed to apply update',
      });
      expect(socket.roomEmit).not.toHaveBeenCalledWith(
        'document-update',
        expect.anything(),
      );
      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });

    it('relays non-string (legacy JSON patch) updates without touching the CRDT', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      const patch = { op: 'replace', path: '/title', value: 'New' };

      await socket.fire('document-update', { documentId: 'doc-1', update: patch });

      expect(socket.roomEmit).toHaveBeenCalledWith('document-update', {
        documentId: 'doc-1',
        update: patch,
      });
      expect(manager.getDocument('doc-1')?.getText('content').toString()).toBe('');
    });

    it('keeps broadcasting when persistence fails and records the error', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await socket.fire('document-update', {
        documentId: 'doc-1',
        update: encodedUpdate('hello'),
      });

      expect(socket.roomEmit).toHaveBeenCalledWith(
        'document-update',
        expect.objectContaining({ documentId: 'doc-1' }),
      );
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'document_persist_failed',
      );
      const persistence = await metrics.persistenceOperations.get();
      expect(persistence.values).toContainEqual(
        expect.objectContaining({
          labels: { operation: 'save_state', status: 'error' },
          value: 1,
        }),
      );
    });
  });

  describe('cursor-update', () => {
    it('broadcasts the cursor of a tracked user', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      socket.roomEmit.mockClear();

      await socket.fire('cursor-update', {
        documentId: 'doc-1',
        cursor: { index: 42, length: 0 },
        selection: null,
      });

      expect(socket.roomEmit).toHaveBeenCalledWith('cursor-update', {
        socketId: 'sock-a',
        userId: 'user-a',
        displayName: 'USER-A',
        color: expect.any(String),
        cursor: { index: 42, length: 0 },
        selection: null,
      });
      const presence = await metrics.presenceUpdatesTotal.get();
      expect(presence.values[0].value).toBe(1);
    });

    it('ignores cursor updates from a socket that never joined', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      io.connect(socket);

      await socket.fire('cursor-update', {
        documentId: 'doc-1',
        cursor: { index: 1, length: 0 },
        selection: null,
      });

      expect(socket.roomEmit).not.toHaveBeenCalled();
    });
  });

  describe('typing-indicator', () => {
    it('broadcasts the typing state of a tracked user', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      socket.roomEmit.mockClear();

      await socket.fire('typing-indicator', { documentId: 'doc-1', isTyping: true });

      expect(socket.to).toHaveBeenCalledWith('doc:doc-1');
      expect(socket.roomEmit).toHaveBeenCalledWith('typing-indicator', {
        socketId: 'sock-a',
        userId: 'user-a',
        displayName: 'USER-A',
        isTyping: true,
      });
    });

    it('ignores typing indicators from a socket that never joined', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      io.connect(socket);

      await socket.fire('typing-indicator', { documentId: 'doc-1', isTyping: false });

      expect(socket.roomEmit).not.toHaveBeenCalled();
    });
  });

  describe('comments', () => {
    it('stamps a new comment with its author and echoes it to everyone', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      socket.emit.mockClear();
      socket.roomEmit.mockClear();

      await socket.fire('comment-add', {
        documentId: 'doc-1',
        comment: {
          id: 'c-1',
          threadId: 't-1',
          content: 'Looks good',
          rangeStart: 0,
          rangeEnd: 5,
        },
      });

      const expected = {
        id: 'c-1',
        threadId: 't-1',
        content: 'Looks good',
        rangeStart: 0,
        rangeEnd: 5,
        documentId: 'doc-1',
        author: { userId: 'user-a', displayName: 'USER-A' },
        createdAt: '2026-01-01T00:00:00.000Z',
      };
      expect(socket.roomEmit).toHaveBeenCalledWith('comment-added', expected);
      expect(socket.emit).toHaveBeenCalledWith('comment-added', expected);
      const comments = await metrics.commentAnnotationsTotal.get();
      expect(comments.values).toContainEqual(
        expect.objectContaining({ labels: { action: 'add' }, value: 1 }),
      );
    });

    it('broadcasts a comment edit with the editor and timestamp', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      socket.roomEmit.mockClear();

      await socket.fire('comment-update', {
        documentId: 'doc-1',
        commentId: 'c-1',
        content: 'Edited',
      });

      expect(socket.roomEmit).toHaveBeenCalledWith('comment-updated', {
        commentId: 'c-1',
        content: 'Edited',
        updatedBy: { userId: 'user-a', displayName: 'USER-A' },
        updatedAt: '2026-01-01T00:00:00.000Z',
      });
    });

    it('broadcasts a comment deletion with the deleting user', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      socket.roomEmit.mockClear();

      await socket.fire('comment-delete', { documentId: 'doc-1', commentId: 'c-1' });

      expect(socket.roomEmit).toHaveBeenCalledWith('comment-deleted', {
        commentId: 'c-1',
        deletedBy: 'user-a',
      });
    });

    it('attributes comments from an unauthenticated socket to an anonymous user', async () => {
      const socket = createFakeSocket('sock-anon');
      await connectAndJoin(socket, 'doc-1');
      socket.emit.mockClear();

      await socket.fire('comment-add', {
        documentId: 'doc-1',
        comment: {
          id: 'c-2',
          threadId: 't-2',
          content: 'Hi',
          rangeStart: 0,
          rangeEnd: 1,
        },
      });

      expect(socket.emit).toHaveBeenCalledWith(
        'comment-added',
        expect.objectContaining({
          author: { userId: 'anon-sock-anon', displayName: 'Anonymous' },
        }),
      );
    });
  });

  describe('request-snapshot', () => {
    it('creates a snapshot and shares it with the room', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      socket.emit.mockClear();
      socket.roomEmit.mockClear();
      const created = snapshot({ label: 'before-edit' });
      documentStore.createSnapshot.mockResolvedValueOnce(created);

      await socket.fire('request-snapshot', {
        documentId: 'doc-1',
        label: 'before-edit',
      });

      expect(documentStore.createSnapshot).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'user-a',
        'before-edit',
      );
      expect(socket.emit).toHaveBeenCalledWith('snapshot-created', created);
      expect(socket.roomEmit).toHaveBeenCalledWith('snapshot-created', created);
    });

    it('creates an unlabelled snapshot when no label is supplied', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');

      await socket.fire('request-snapshot', { documentId: 'doc-1' });

      expect(documentStore.createSnapshot).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'user-a',
        undefined,
      );
    });

    it('reports an error for a document that is not loaded', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      io.connect(socket);

      await socket.fire('request-snapshot', { documentId: 'doc-missing' });

      expect(socket.emit).toHaveBeenCalledWith('snapshot-error', {
        documentId: 'doc-missing',
        error: 'Document not found',
      });
      expect(documentStore.createSnapshot).not.toHaveBeenCalled();
    });

    it('reports an error when the store rejects', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      socket.emit.mockClear();
      documentStore.createSnapshot.mockRejectedValueOnce(new Error('redis down'));

      await socket.fire('request-snapshot', { documentId: 'doc-1' });

      expect(socket.emit).toHaveBeenCalledWith('snapshot-error', {
        documentId: 'doc-1',
        error: 'Failed to create snapshot',
      });
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'create_snapshot_failed',
      );
    });
  });

  describe('request-history', () => {
    it('returns the stored snapshots with the default limit', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      io.connect(socket);
      const history = [snapshot({ id: 'snap-1' }), snapshot({ id: 'snap-2' })];
      documentStore.getSnapshots.mockResolvedValueOnce(history);

      await socket.fire('request-history', { documentId: 'doc-1' });

      expect(documentStore.getSnapshots).toHaveBeenCalledWith('doc-1', 20);
      expect(socket.emit).toHaveBeenCalledWith('document-history', {
        documentId: 'doc-1',
        snapshots: history,
      });
    });

    it('honours an explicit limit', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      io.connect(socket);

      await socket.fire('request-history', { documentId: 'doc-1', limit: 5 });

      expect(documentStore.getSnapshots).toHaveBeenCalledWith('doc-1', 5);
    });

    it('reports an error when the store rejects', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      io.connect(socket);
      documentStore.getSnapshots.mockRejectedValueOnce(new Error('redis down'));

      await socket.fire('request-history', { documentId: 'doc-1' });

      expect(socket.emit).toHaveBeenCalledWith('history-error', {
        documentId: 'doc-1',
        error: 'Failed to retrieve history',
      });
    });
  });

  describe('leave-document', () => {
    it('removes the user, notifies the room and evicts the empty document', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      socket.roomEmit.mockClear();
      documentStore.saveDocumentState.mockClear();

      await socket.fire('leave-document', { documentId: 'doc-1' });

      expect(socket.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(socket.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 'sock-a',
        userId: 'user-a',
      });
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
      expect(manager.getDocumentCount()).toBe(0);
    });

    it('keeps the document in memory while other users remain', async () => {
      const first = createFakeSocket('sock-a', 'user-a');
      const second = createFakeSocket('sock-b', 'user-b');
      await connectAndJoin(first, 'doc-1');
      await connectAndJoin(second, 'doc-1');
      documentStore.saveDocumentState.mockClear();

      await first.fire('leave-document', { documentId: 'doc-1' });

      expect(manager.getDocumentCount()).toBe(1);
      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });

    it('falls back to the client-provided document id for an untracked socket', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      io.connect(socket);

      await socket.fire('leave-document', { documentId: 'doc-ghost' });

      expect(socket.leave).toHaveBeenCalledWith('doc:doc-ghost');
      expect(socket.roomEmit).not.toHaveBeenCalled();
      expect(logger.info).toHaveBeenCalledWith(
        { documentId: 'doc-ghost', socketId: 'sock-a' },
        'user_left_document',
      );
    });
  });

  describe('disconnect', () => {
    it('cleans up awareness, notifies the room and persists the empty document', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      socket.roomEmit.mockClear();
      documentStore.saveDocumentState.mockClear();

      await socket.fire('disconnect', 'transport close');

      expect(socket.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 'sock-a',
        userId: 'user-a',
      });
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
      const gauge = await metrics.activeConnections.get();
      expect(gauge.values[0].value).toBe(0);
    });

    it('does nothing beyond the connection count for a socket that never joined', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      io.connect(socket);

      await socket.fire('disconnect', 'client namespace disconnect');

      expect(socket.roomEmit).not.toHaveBeenCalled();
      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });
  });

  describe('persistAndCleanupDocument', () => {
    it('is a no-op for a document that is not in memory', async () => {
      await manager.persistAndCleanupDocument('doc-missing');

      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });

    it('runs only once for concurrent cleanups of the same document', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      awareness.removeUser('sock-a');
      documentStore.saveDocumentState.mockClear();
      let release: (() => void) | undefined;
      documentStore.saveDocumentState.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            release = () => resolve();
          }),
      );

      const cleanups = Promise.all([
        manager.persistAndCleanupDocument('doc-1'),
        manager.persistAndCleanupDocument('doc-1'),
      ]);
      release?.();
      await cleanups;

      expect(documentStore.saveDocumentState).toHaveBeenCalledTimes(1);
      expect(manager.getDocumentCount()).toBe(0);
    });

    it('keeps the document in memory when persistence fails', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      awareness.removeUser('sock-a');
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await manager.persistAndCleanupDocument('doc-1');

      expect(manager.getDocumentCount()).toBe(1);
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'document_persist_on_cleanup_failed',
      );
    });

    it('keeps the document in memory when a user re-joined during persistence', async () => {
      const first = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(first, 'doc-1');
      awareness.removeUser('sock-a');
      documentStore.saveDocumentState.mockImplementationOnce(async () => {
        awareness.addUser('doc-1', 'sock-b', 'user-b', 'Bob', 'b@test.com');
      });

      await manager.persistAndCleanupDocument('doc-1');

      expect(manager.getDocumentCount()).toBe(1);
    });
  });

  describe('periodic loops', () => {
    it('persists every in-memory document on the persistence interval', async () => {
      await manager.stop();
      manager = build({ persistIntervalMs: 1000, snapshotIntervalMs: 900000 });
      manager.start();
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      documentStore.saveDocumentState.mockClear();

      await jest.advanceTimersByTimeAsync(1000);

      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
      const persistence = await metrics.persistenceOperations.get();
      expect(persistence.values).toContainEqual(
        expect.objectContaining({
          labels: { operation: 'periodic_save', status: 'success' },
          value: 1,
        }),
      );
    });

    it('records a failed periodic persistence without stopping the loop', async () => {
      await manager.stop();
      manager = build({ persistIntervalMs: 1000, snapshotIntervalMs: 900000 });
      manager.start();
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await jest.advanceTimersByTimeAsync(1000);
      await jest.advanceTimersByTimeAsync(1000);

      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'periodic_persistence_failed',
      );
      const persistence = await metrics.persistenceOperations.get();
      expect(persistence.values).toContainEqual(
        expect.objectContaining({
          labels: { operation: 'periodic_save', status: 'error' },
          value: 1,
        }),
      );
      expect(persistence.values).toContainEqual(
        expect.objectContaining({
          labels: { operation: 'periodic_save', status: 'success' },
          value: 1,
        }),
      );
    });

    it('takes an automatic snapshot on the snapshot interval', async () => {
      await manager.stop();
      manager = build({ persistIntervalMs: 900000, snapshotIntervalMs: 1000 });
      manager.start();
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');

      await jest.advanceTimersByTimeAsync(1000);

      expect(documentStore.createSnapshot).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'system',
        'auto-snapshot',
      );
    });

    it('logs a failed automatic snapshot', async () => {
      await manager.stop();
      manager = build({ persistIntervalMs: 900000, snapshotIntervalMs: 1000 });
      manager.start();
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      documentStore.createSnapshot.mockRejectedValueOnce(new Error('redis down'));

      await jest.advanceTimersByTimeAsync(1000);

      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'periodic_snapshot_failed',
      );
    });
  });

  describe('stop', () => {
    it('flushes every document and stops the timers', async () => {
      await manager.stop();
      manager = build({ persistIntervalMs: 1000, snapshotIntervalMs: 1000 });
      manager.start();
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      documentStore.saveDocumentState.mockClear();

      await manager.stop();
      await jest.advanceTimersByTimeAsync(5000);

      expect(documentStore.saveDocumentState).toHaveBeenCalledTimes(1);
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
      expect(logger.info).toHaveBeenCalledWith('collaboration_manager_stopped');
    });

    it('logs a failed shutdown flush and still completes', async () => {
      const socket = createFakeSocket('sock-a', 'user-a');
      await connectAndJoin(socket, 'doc-1');
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await expect(manager.stop()).resolves.toBeUndefined();

      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'document_persist_on_shutdown_failed',
      );
    });

    it('is safe to call before the manager was started', async () => {
      const idle = build();

      await expect(idle.stop()).resolves.toBeUndefined();
    });
  });
});

describe('setupCollaborationHandlers', () => {
  it('builds a started manager wired to the supplied dependencies', async () => {
    const io = createFakeIo();
    const logger = createLogger();
    const metrics = new MetricsCollector();
    const awareness = new AwarenessService(logger);
    const presenceHandler = new PresenceHandler(awareness, logger);
    const documentStore = createDocumentStore();

    const manager = setupCollaborationHandlers(
      io.server,
      documentStore,
      awareness,
      presenceHandler,
      metrics,
      logger,
    );

    const socket = createFakeSocket('sock-a', 'user-a');
    io.connect(socket);
    await socket.fire('join-document', { documentId: 'doc-1' }, () => {});

    expect(manager).toBeInstanceOf(CollaborationManager);
    expect(manager.getDocumentCount()).toBe(1);
    expect(logger.info).toHaveBeenCalledWith('collaboration_manager_started');

    await manager.stop();
    metrics.registry.clear();
  });
});
