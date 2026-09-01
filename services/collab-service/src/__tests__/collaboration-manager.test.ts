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

type Emission = { event: string; payload: unknown };
type RoomEmission = Emission & { room: string };

class FakeSocket {
  readonly emitted: Emission[] = [];
  readonly roomEmitted: RoomEmission[] = [];
  readonly joined: string[] = [];
  readonly left: string[] = [];
  private readonly handlers = new Map<string, (...args: never[]) => unknown>();

  constructor(
    readonly id: string,
    user?: { userId: string; displayName: string; email: string },
  ) {
    if (user) {
      (this as unknown as AuthenticatedSocket).user = { ...user, roles: [] };
    }
  }

  on(event: string, handler: (...args: never[]) => unknown): this {
    this.handlers.set(event, handler);
    return this;
  }

  emit(event: string, payload?: unknown): boolean {
    this.emitted.push({ event, payload });
    return true;
  }

  to(room: string) {
    return {
      emit: (event: string, payload?: unknown) => {
        this.roomEmitted.push({ room, event, payload });
        return true;
      },
    };
  }

  async join(room: string): Promise<void> {
    this.joined.push(room);
  }

  leave(room: string): void {
    this.left.push(room);
  }

  trigger(event: string, ...args: unknown[]): unknown {
    const handler = this.handlers.get(event);
    if (!handler) throw new Error(`no handler registered for '${event}'`);
    return handler(...(args as never[]));
  }

  hasHandler(event: string): boolean {
    return this.handlers.has(event);
  }

  emissions(event: string): unknown[] {
    return this.emitted.filter((e) => e.event === event).map((e) => e.payload);
  }

  asSocket(): Socket {
    return this as unknown as Socket;
  }
}

function createLoggerMock() {
  return {
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
    debug: jest.fn(),
  };
}

function createDocumentStoreMock() {
  return {
    getDocumentState: jest.fn().mockResolvedValue(null),
    saveDocumentState: jest.fn().mockResolvedValue(undefined),
    createSnapshot: jest.fn().mockResolvedValue({ id: 'snap-1' }),
    getSnapshots: jest.fn().mockResolvedValue([]),
  };
}

function encodeUpdate(text: string): string {
  const doc = new Y.Doc();
  doc.getText('content').insert(0, text);
  return Buffer.from(Y.encodeStateAsUpdate(doc)).toString('base64');
}

describe('CollaborationManager', () => {
  let logger: ReturnType<typeof createLoggerMock>;
  let documentStore: ReturnType<typeof createDocumentStoreMock>;
  let awareness: AwarenessService;
  let presenceHandler: PresenceHandler;
  let metrics: MetricsCollector;
  let manager: CollaborationManager;
  let ioRoomEmissions: RoomEmission[];
  let io: SocketIOServer;
  let connectionHandler: (socket: Socket) => void;

  function buildManager(overrides?: { persistIntervalMs?: number }) {
    return new CollaborationManager({
      io,
      documentStore: documentStore as unknown as DocumentStore,
      awareness,
      presenceHandler,
      metrics,
      logger: logger as unknown as Logger,
      persistIntervalMs: overrides?.persistIntervalMs ?? 600000,
      snapshotIntervalMs: 600000,
    });
  }

  async function connectAndJoin(
    socket: FakeSocket,
    documentId: string,
  ): Promise<{ success: boolean; error?: string }> {
    connectionHandler(socket.asSocket());
    return new Promise((resolve) => {
      socket.trigger('join-document', { documentId }, resolve);
    });
  }

  beforeEach(() => {
    jest.clearAllMocks();
    logger = createLoggerMock();
    documentStore = createDocumentStoreMock();
    awareness = new AwarenessService(logger as unknown as Logger);
    presenceHandler = new PresenceHandler(awareness, logger as unknown as Logger);
    metrics = new MetricsCollector();
    ioRoomEmissions = [];
    io = {
      on: jest.fn((event: string, handler: (socket: Socket) => void) => {
        if (event === 'connection') connectionHandler = handler;
      }),
      to: (room: string) => ({
        emit: (event: string, payload?: unknown) => {
          ioRoomEmissions.push({ room, event, payload });
          return true;
        },
      }),
      sockets: { sockets: new Map() },
    } as unknown as SocketIOServer;

    manager = buildManager();
    manager.start();
  });

  afterEach(async () => {
    await manager.stop();
    metrics.registry.clear();
    jest.useRealTimers();
  });

  describe('start', () => {
    it('registers every socket event handler on connection', () => {
      const socket = new FakeSocket('socket-1');

      connectionHandler(socket.asSocket());

      for (const event of [
        'join-document',
        'leave-document',
        'document-update',
        'cursor-update',
        'typing-indicator',
        'comment-add',
        'comment-update',
        'comment-delete',
        'request-snapshot',
        'request-history',
        'disconnect',
      ]) {
        expect(socket.hasHandler(event)).toBe(true);
      }
    });
  });

  describe('join-document', () => {
    it('joins the room, syncs state and announces the new user', async () => {
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });

      const ack = await connectAndJoin(socket, 'doc-1');

      expect(ack).toEqual({ success: true });
      expect(socket.joined).toEqual(['doc:doc-1']);
      expect(socket.emissions('sync-document')[0]).toMatchObject({
        documentId: 'doc-1',
      });
      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-1',
        event: 'user-joined',
        payload: expect.objectContaining({ userId: 'user-1', displayName: 'Alice' }),
      });
      expect(ioRoomEmissions).toContainEqual(
        expect.objectContaining({ room: 'doc:doc-1', event: 'presence-update' }),
      );
      expect(manager.getDocumentCount()).toBe(1);
    });

    it('rehydrates persisted document state on first join', async () => {
      const seeded = new Y.Doc();
      seeded.getText('content').insert(0, 'persisted');
      documentStore.getDocumentState.mockResolvedValueOnce(
        new Uint8Array(Y.encodeStateAsUpdate(seeded)),
      );
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });

      await connectAndJoin(socket, 'doc-1');

      expect(manager.getDocument('doc-1')?.getText('content').toString()).toBe(
        'persisted',
      );
    });

    it('reuses one in-memory document for concurrent joins', async () => {
      const first = new FakeSocket('socket-1');
      const second = new FakeSocket('socket-2');
      connectionHandler(first.asSocket());
      connectionHandler(second.asSocket());

      await Promise.all([
        new Promise((resolve) =>
          first.trigger('join-document', { documentId: 'doc-1' }, resolve),
        ),
        new Promise((resolve) =>
          second.trigger('join-document', { documentId: 'doc-1' }, resolve),
        ),
      ]);

      expect(documentStore.getDocumentState).toHaveBeenCalledTimes(1);
      expect(manager.getDocumentCount()).toBe(1);
      expect(awareness.getDocumentUserCount('doc-1')).toBe(2);
    });

    it('leaves the previous document and cleans it up when the user switches', async () => {
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      await connectAndJoin(socket, 'doc-old');

      await new Promise((resolve) =>
        socket.trigger('join-document', { documentId: 'doc-new' }, resolve),
      );

      expect(socket.left).toContain('doc:doc-old');
      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-old',
        event: 'user-left',
        payload: { socketId: 'socket-1', userId: 'user-1' },
      });
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-old',
        expect.any(Buffer),
      );
      expect(awareness.getUserDocument('socket-1')).toBe('doc-new');
    });

    it('keeps the previous document in memory when other users remain', async () => {
      const alice = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      const bob = new FakeSocket('socket-2', {
        userId: 'user-2',
        displayName: 'Bob',
        email: 'b@test.com',
      });
      await connectAndJoin(alice, 'doc-old');
      await connectAndJoin(bob, 'doc-old');

      await new Promise((resolve) =>
        alice.trigger('join-document', { documentId: 'doc-new' }, resolve),
      );

      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
      expect(manager.getDocument('doc-old')).toBeDefined();
    });

    it('acknowledges failure and leaves the room when loading state fails', async () => {
      documentStore.getDocumentState.mockRejectedValueOnce(new Error('redis down'));
      const socket = new FakeSocket('socket-1');

      const ack = await connectAndJoin(socket, 'doc-1');

      expect(ack).toEqual({ success: false, error: 'Failed to join document' });
      expect(socket.left).toContain('doc:doc-1');
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'join_document_failed',
      );
    });

    it('joins without an acknowledgement callback', async () => {
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());

      await socket.trigger('join-document', { documentId: 'doc-1' });

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });

    it('swallows a failed join that has no acknowledgement callback', async () => {
      documentStore.getDocumentState.mockRejectedValueOnce(new Error('redis down'));
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());

      await socket.trigger('join-document', { documentId: 'doc-1' });

      expect(socket.emissions('sync-document')).toHaveLength(0);
    });
  });

  describe('leave-document', () => {
    it('removes the user, notifies the room and persists the emptied document', async () => {
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      await connectAndJoin(socket, 'doc-1');

      socket.trigger('leave-document', { documentId: 'doc-1' });
      await Promise.resolve();
      await Promise.resolve();

      expect(socket.left).toContain('doc:doc-1');
      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-1',
        event: 'user-left',
        payload: { socketId: 'socket-1', userId: 'user-1' },
      });
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
    });

    it('falls back to the client-supplied document id for an untracked socket', () => {
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());

      socket.trigger('leave-document', { documentId: 'doc-ghost' });

      expect(socket.left).toEqual(['doc:doc-ghost']);
      expect(socket.roomEmitted).toHaveLength(0);
    });
  });

  describe('document-update', () => {
    it('applies a base64 Yjs update, broadcasts it and persists the new state', async () => {
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      await connectAndJoin(socket, 'doc-1');
      const update = encodeUpdate('hello');

      await socket.trigger('document-update', { documentId: 'doc-1', update });

      expect(manager.getDocument('doc-1')?.getText('content').toString()).toBe('hello');
      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-1',
        event: 'document-update',
        payload: { documentId: 'doc-1', update },
      });
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'user-1',
      );
    });

    it('broadcasts non-string (legacy JSON) updates without touching the CRDT', async () => {
      const socket = new FakeSocket('socket-1');
      await connectAndJoin(socket, 'doc-1');
      const update = { op: 'replace', value: 'x' };

      await socket.trigger('document-update', { documentId: 'doc-1', update });

      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-1',
        event: 'document-update',
        payload: { documentId: 'doc-1', update },
      });
    });

    it('ignores updates for a document that is not loaded', async () => {
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());

      await socket.trigger('document-update', {
        documentId: 'doc-unknown',
        update: encodeUpdate('hello'),
      });

      expect(logger.warn).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-unknown' }),
        'document_update_for_unknown_doc',
      );
      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });

    it('reports an update that cannot be applied to the CRDT', async () => {
      const socket = new FakeSocket('socket-1');
      await connectAndJoin(socket, 'doc-1');

      await socket.trigger('document-update', {
        documentId: 'doc-1',
        update: Buffer.from([255, 255, 255, 255, 255, 255]).toString('base64'),
      });

      expect(socket.emissions('document-update-error')[0]).toEqual({
        documentId: 'doc-1',
        error: 'Failed to apply update',
      });
      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });

    it('keeps broadcasting when persistence fails', async () => {
      const socket = new FakeSocket('socket-1');
      await connectAndJoin(socket, 'doc-1');
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await socket.trigger('document-update', {
        documentId: 'doc-1',
        update: encodeUpdate('hello'),
      });

      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'document_persist_failed',
      );
    });
  });

  describe('cursor-update and typing-indicator', () => {
    it('broadcasts a cursor update for a tracked socket', async () => {
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      await connectAndJoin(socket, 'doc-1');
      const cursor = { index: 42, length: 0 };

      socket.trigger('cursor-update', { documentId: 'doc-1', cursor, selection: null });

      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-1',
        event: 'cursor-update',
        payload: expect.objectContaining({
          socketId: 'socket-1',
          userId: 'user-1',
          cursor,
          selection: null,
        }),
      });
    });

    it('ignores a cursor update from an untracked socket', () => {
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());

      socket.trigger('cursor-update', {
        documentId: 'doc-1',
        cursor: null,
        selection: null,
      });

      expect(socket.roomEmitted).toHaveLength(0);
    });

    it('broadcasts a typing indicator for a tracked socket', async () => {
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      await connectAndJoin(socket, 'doc-1');

      socket.trigger('typing-indicator', { documentId: 'doc-1', isTyping: true });

      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-1',
        event: 'typing-indicator',
        payload: {
          socketId: 'socket-1',
          userId: 'user-1',
          displayName: 'Alice',
          isTyping: true,
        },
      });
    });

    it('ignores a typing indicator from an untracked socket', () => {
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());

      socket.trigger('typing-indicator', { documentId: 'doc-1', isTyping: false });

      expect(socket.roomEmitted).toHaveLength(0);
    });
  });

  describe('comments', () => {
    it('stamps the author and echoes a new comment to the room and the author', () => {
      jest.useFakeTimers().setSystemTime(new Date('2026-01-01T00:00:00Z'));
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      connectionHandler(socket.asSocket());

      socket.trigger('comment-add', {
        documentId: 'doc-1',
        comment: {
          id: 'c-1',
          threadId: 't-1',
          content: 'looks good',
          rangeStart: 0,
          rangeEnd: 4,
        },
      });

      const expected = {
        id: 'c-1',
        documentId: 'doc-1',
        threadId: 't-1',
        content: 'looks good',
        rangeStart: 0,
        rangeEnd: 4,
        author: { userId: 'user-1', displayName: 'Alice' },
        createdAt: '2026-01-01T00:00:00.000Z',
      };
      expect(socket.emissions('comment-added')[0]).toEqual(expected);
      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-1',
        event: 'comment-added',
        payload: expected,
      });
    });

    it('broadcasts comment edits with the editor and timestamp', () => {
      jest.useFakeTimers().setSystemTime(new Date('2026-01-01T00:00:00Z'));
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      connectionHandler(socket.asSocket());

      socket.trigger('comment-update', {
        documentId: 'doc-1',
        commentId: 'c-1',
        content: 'edited',
      });

      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-1',
        event: 'comment-updated',
        payload: {
          commentId: 'c-1',
          content: 'edited',
          updatedBy: { userId: 'user-1', displayName: 'Alice' },
          updatedAt: '2026-01-01T00:00:00.000Z',
        },
      });
    });

    it('broadcasts comment deletions with the deleting user', () => {
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      connectionHandler(socket.asSocket());

      socket.trigger('comment-delete', { documentId: 'doc-1', commentId: 'c-1' });

      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-1',
        event: 'comment-deleted',
        payload: { commentId: 'c-1', deletedBy: 'user-1' },
      });
    });
  });

  describe('snapshots and history', () => {
    it('creates a snapshot and shares it with the room', async () => {
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      await connectAndJoin(socket, 'doc-1');

      await socket.trigger('request-snapshot', {
        documentId: 'doc-1',
        label: 'before-edit',
      });

      expect(documentStore.createSnapshot).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'user-1',
        'before-edit',
      );
      expect(socket.emissions('snapshot-created')[0]).toEqual({ id: 'snap-1' });
      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-1',
        event: 'snapshot-created',
        payload: { id: 'snap-1' },
      });
    });

    it('rejects a snapshot request for a document that is not loaded', async () => {
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());

      await socket.trigger('request-snapshot', { documentId: 'doc-unknown' });

      expect(socket.emissions('snapshot-error')[0]).toEqual({
        documentId: 'doc-unknown',
        error: 'Document not found',
      });
      expect(documentStore.createSnapshot).not.toHaveBeenCalled();
    });

    it('reports a snapshot store failure to the requester', async () => {
      const socket = new FakeSocket('socket-1');
      await connectAndJoin(socket, 'doc-1');
      documentStore.createSnapshot.mockRejectedValueOnce(new Error('redis down'));

      await socket.trigger('request-snapshot', { documentId: 'doc-1' });

      expect(socket.emissions('snapshot-error')[0]).toEqual({
        documentId: 'doc-1',
        error: 'Failed to create snapshot',
      });
    });

    it.each([
      [{ documentId: 'doc-1', limit: 5 }, 5],
      [{ documentId: 'doc-1' }, 20],
    ])('serves history for %o using limit %i', async (data, expectedLimit) => {
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());
      documentStore.getSnapshots.mockResolvedValueOnce([{ id: 'snap-1' }]);

      await socket.trigger('request-history', data);

      expect(documentStore.getSnapshots).toHaveBeenCalledWith('doc-1', expectedLimit);
      expect(socket.emissions('document-history')[0]).toEqual({
        documentId: 'doc-1',
        snapshots: [{ id: 'snap-1' }],
      });
    });

    it('reports a history lookup failure to the requester', async () => {
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());
      documentStore.getSnapshots.mockRejectedValueOnce(new Error('redis down'));

      await socket.trigger('request-history', { documentId: 'doc-1' });

      expect(socket.emissions('history-error')[0]).toEqual({
        documentId: 'doc-1',
        error: 'Failed to retrieve history',
      });
    });
  });

  describe('disconnect', () => {
    it('notifies the room and cleans up the emptied document', async () => {
      const socket = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      await connectAndJoin(socket, 'doc-1');

      socket.trigger('disconnect', 'transport close');
      await Promise.resolve();
      await Promise.resolve();

      expect(socket.roomEmitted).toContainEqual({
        room: 'doc:doc-1',
        event: 'user-left',
        payload: { socketId: 'socket-1', userId: 'user-1' },
      });
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
    });

    it('keeps the document when other users are still connected', async () => {
      const alice = new FakeSocket('socket-1', {
        userId: 'user-1',
        displayName: 'Alice',
        email: 'a@test.com',
      });
      const bob = new FakeSocket('socket-2', {
        userId: 'user-2',
        displayName: 'Bob',
        email: 'b@test.com',
      });
      await connectAndJoin(alice, 'doc-1');
      await connectAndJoin(bob, 'doc-1');

      alice.trigger('disconnect', 'client namespace disconnect');
      await Promise.resolve();

      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
      expect(manager.getDocument('doc-1')).toBeDefined();
    });

    it('ignores a disconnect from a socket that never joined a document', () => {
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());

      socket.trigger('disconnect', 'transport error');

      expect(socket.roomEmitted).toHaveLength(0);
    });
  });

  describe('persistAndCleanupDocument', () => {
    it('is a no-op for a document that is not in memory', async () => {
      await manager.persistAndCleanupDocument('doc-unknown');

      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });

    it('keeps the document in memory when a user re-joined during persistence', async () => {
      const alice = new FakeSocket('socket-1');
      await connectAndJoin(alice, 'doc-1');
      awareness.removeUser('socket-1');
      documentStore.saveDocumentState.mockImplementationOnce(async () => {
        awareness.addUser('doc-1', 'socket-2', 'user-2', 'Bob', 'b@test.com');
      });

      await manager.persistAndCleanupDocument('doc-1');

      expect(manager.getDocument('doc-1')).toBeDefined();
    });

    it('keeps the document in memory when persistence fails so the loop can retry', async () => {
      const socket = new FakeSocket('socket-1');
      await connectAndJoin(socket, 'doc-1');
      awareness.removeUser('socket-1');
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await manager.persistAndCleanupDocument('doc-1');

      expect(manager.getDocument('doc-1')).toBeDefined();
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'document_persist_on_cleanup_failed',
      );
    });

    it('ignores a second cleanup while the first is still running', async () => {
      const socket = new FakeSocket('socket-1');
      await connectAndJoin(socket, 'doc-1');
      awareness.removeUser('socket-1');
      let release: () => void = () => undefined;
      documentStore.saveDocumentState.mockImplementationOnce(
        () => new Promise<void>((resolve) => (release = resolve)),
      );

      const first = manager.persistAndCleanupDocument('doc-1');
      await manager.persistAndCleanupDocument('doc-1');
      release();
      await first;

      expect(documentStore.saveDocumentState).toHaveBeenCalledTimes(1);
      expect(manager.getDocument('doc-1')).toBeUndefined();
    });
  });

  describe('background loops', () => {
    it('persists every in-memory document on each tick', async () => {
      jest.useFakeTimers();
      await manager.stop();
      manager = buildManager({ persistIntervalMs: 1000 });
      manager.start();
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());
      await socket.trigger('join-document', { documentId: 'doc-1' });

      await jest.advanceTimersByTimeAsync(1000);

      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
    });

    it('logs and continues when a periodic save fails', async () => {
      jest.useFakeTimers();
      await manager.stop();
      manager = buildManager({ persistIntervalMs: 1000 });
      manager.start();
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());
      await socket.trigger('join-document', { documentId: 'doc-1' });
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await jest.advanceTimersByTimeAsync(1000);

      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'periodic_persistence_failed',
      );
    });

    it('takes an automatic snapshot of every document on each snapshot tick', async () => {
      jest.useFakeTimers();
      await manager.stop();
      manager = new CollaborationManager({
        io,
        documentStore: documentStore as unknown as DocumentStore,
        awareness,
        presenceHandler,
        metrics,
        logger: logger as unknown as Logger,
        persistIntervalMs: 600000,
        snapshotIntervalMs: 1000,
      });
      manager.start();
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());
      await socket.trigger('join-document', { documentId: 'doc-1' });

      await jest.advanceTimersByTimeAsync(1000);

      expect(documentStore.createSnapshot).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'system',
        'auto-snapshot',
      );
    });

    it('logs and continues when an automatic snapshot fails', async () => {
      jest.useFakeTimers();
      await manager.stop();
      manager = new CollaborationManager({
        io,
        documentStore: documentStore as unknown as DocumentStore,
        awareness,
        presenceHandler,
        metrics,
        logger: logger as unknown as Logger,
        persistIntervalMs: 600000,
        snapshotIntervalMs: 1000,
      });
      manager.start();
      const socket = new FakeSocket('socket-1');
      connectionHandler(socket.asSocket());
      await socket.trigger('join-document', { documentId: 'doc-1' });
      documentStore.createSnapshot.mockRejectedValueOnce(new Error('redis down'));

      await jest.advanceTimersByTimeAsync(1000);

      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'periodic_snapshot_failed',
      );
    });
  });

  describe('stop', () => {
    it('flushes every in-memory document before shutting down', async () => {
      const socket = new FakeSocket('socket-1');
      await connectAndJoin(socket, 'doc-1');

      await manager.stop();

      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
      expect(logger.info).toHaveBeenCalledWith(
        { documentId: 'doc-1' },
        'document_persisted_on_shutdown',
      );
    });

    it('logs a failed shutdown flush without throwing', async () => {
      const socket = new FakeSocket('socket-1');
      await connectAndJoin(socket, 'doc-1');
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await expect(manager.stop()).resolves.toBeUndefined();

      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'document_persist_on_shutdown_failed',
      );
    });
  });
});

describe('setupCollaborationHandlers', () => {
  it('builds a started manager with the default intervals', async () => {
    const logger = createLoggerMock();
    const documentStore = createDocumentStoreMock();
    const awareness = new AwarenessService(logger as unknown as Logger);
    const presenceHandler = new PresenceHandler(awareness, logger as unknown as Logger);
    const metrics = new MetricsCollector();
    const io = {
      on: jest.fn(),
      to: () => ({ emit: jest.fn() }),
      sockets: { sockets: new Map() },
    } as unknown as SocketIOServer;

    const manager = setupCollaborationHandlers(
      io,
      documentStore as unknown as DocumentStore,
      awareness,
      presenceHandler,
      metrics,
      logger as unknown as Logger,
    );

    expect(manager).toBeInstanceOf(CollaborationManager);
    expect(io.on).toHaveBeenCalledWith('connection', expect.any(Function));
    expect(manager.getDocumentCount()).toBe(0);

    await manager.stop();
    metrics.registry.clear();
  });
});
