import type { Logger } from 'pino';
import type { Server as SocketIOServer, Socket } from 'socket.io';
import * as Y from 'yjs';
import {
  CollaborationManager,
  setupCollaborationHandlers,
} from '../handlers/collaboration';
import { PresenceHandler } from '../handlers/presence';
import { AwarenessService } from '../services/awareness';
import type { DocumentStore, DocumentSnapshot } from '../services/document-store';
import { MetricsCollector } from '../metrics';
import type { AuthenticatedUser } from '../middleware/auth';

type Handler = (...args: never[]) => unknown;

interface RoomEmit {
  room: string;
  event: string;
  payload: unknown;
}

class FakeSocket {
  readonly handlers = new Map<string, Handler>();
  readonly emitted: Array<{ event: string; payload: unknown }> = [];
  readonly roomEmits: RoomEmit[] = [];
  readonly joined: string[] = [];
  readonly left: string[] = [];
  joinError: Error | null = null;
  user?: AuthenticatedUser;

  constructor(readonly id: string) {}

  on(event: string, handler: Handler): this {
    this.handlers.set(event, handler);
    return this;
  }

  emit(event: string, payload: unknown): boolean {
    this.emitted.push({ event, payload });
    return true;
  }

  async join(room: string): Promise<void> {
    if (this.joinError) throw this.joinError;
    this.joined.push(room);
  }

  leave(room: string): void {
    this.left.push(room);
  }

  to(room: string) {
    return {
      emit: (event: string, payload: unknown) => {
        this.roomEmits.push({ room, event, payload });
        return true;
      },
    };
  }

  trigger(event: string, ...args: unknown[]): unknown {
    const handler = this.handlers.get(event);
    if (!handler) throw new Error(`no handler registered for "${event}"`);
    return (handler as (...a: unknown[]) => unknown)(...args);
  }

  eventsNamed(event: string): unknown[] {
    return this.emitted.filter((e) => e.event === event).map((e) => e.payload);
  }

  roomEventsNamed(event: string): RoomEmit[] {
    return this.roomEmits.filter((e) => e.event === event);
  }

  asSocket(): Socket {
    return this as unknown as Socket;
  }
}

function encodeUpdate(content: string): string {
  const doc = new Y.Doc();
  doc.getText('content').insert(0, content);
  return Buffer.from(Y.encodeStateAsUpdate(doc)).toString('base64');
}

function stateBufferFor(content: string): Uint8Array {
  const doc = new Y.Doc();
  doc.getText('content').insert(0, content);
  return Y.encodeStateAsUpdate(doc);
}

const logger = {
  info: jest.fn(),
  debug: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
} as unknown as Logger;

const SNAPSHOT: DocumentSnapshot = {
  id: 'snap-1',
  documentId: 'doc-1',
  state: 'AAA=',
  createdAt: '2026-01-01T00:00:00.000Z',
  createdBy: 'user-1',
};

describe('CollaborationManager', () => {
  let manager: CollaborationManager;
  let awareness: AwarenessService;
  let presenceHandler: PresenceHandler;
  let metrics: MetricsCollector;
  let ioRoomEmits: RoomEmit[];
  let io: SocketIOServer;
  let connectionHandler: (socket: Socket) => void;
  let documentStore: {
    getDocumentState: jest.Mock;
    saveDocumentState: jest.Mock;
    createSnapshot: jest.Mock;
    getSnapshots: jest.Mock;
  };

  function buildManager(overrides?: {
    persistIntervalMs?: number;
  }): CollaborationManager {
    return new CollaborationManager({
      io,
      documentStore: documentStore as unknown as DocumentStore,
      awareness,
      presenceHandler,
      metrics,
      logger,
      persistIntervalMs: overrides?.persistIntervalMs ?? 30000,
      snapshotIntervalMs: 300000,
    });
  }

  async function connect(id: string): Promise<FakeSocket> {
    const socket = new FakeSocket(id);
    socket.user = {
      userId: `user-${id}`,
      email: `${id}@test.com`,
      displayName: `Name ${id}`,
      roles: ['editor'],
    };
    connectionHandler(socket.asSocket());
    return socket;
  }

  async function join(socket: FakeSocket, documentId: string): Promise<void> {
    await socket.trigger('join-document', { documentId }, () => {});
  }

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));

    ioRoomEmits = [];
    io = {
      on: jest.fn((event: string, handler: (socket: Socket) => void) => {
        if (event === 'connection') connectionHandler = handler;
      }),
      to: (room: string) => ({
        emit: (event: string, payload: unknown) =>
          ioRoomEmits.push({ room, event, payload }),
      }),
      sockets: { sockets: new Map() },
    } as unknown as SocketIOServer;

    documentStore = {
      getDocumentState: jest.fn().mockResolvedValue(null),
      saveDocumentState: jest.fn().mockResolvedValue(undefined),
      createSnapshot: jest.fn().mockResolvedValue(SNAPSHOT),
      getSnapshots: jest.fn().mockResolvedValue([SNAPSHOT]),
    };

    awareness = new AwarenessService(logger);
    presenceHandler = new PresenceHandler(awareness, logger);
    metrics = new MetricsCollector();

    manager = buildManager();
    manager.start();
  });

  afterEach(async () => {
    await manager.stop();
    jest.clearAllTimers();
    jest.useRealTimers();
    metrics.registry.clear();
  });

  describe('start', () => {
    it('subscribes to connections and counts them', async () => {
      const socket = await connect('sock-1');

      expect(io.on).toHaveBeenCalledWith('connection', expect.any(Function));
      expect(await metrics.getMetrics()).toContain('collab_active_connections 1');
      expect(socket.handlers.has('join-document')).toBe(true);
      expect(socket.handlers.has('disconnect')).toBe(true);
    });
  });

  describe('join-document', () => {
    it('joins the room, syncs state and announces the user', async () => {
      const socket = await connect('sock-1');
      const ack = jest.fn();

      await socket.trigger('join-document', { documentId: 'doc-1' }, ack);

      expect(socket.joined).toEqual(['doc:doc-1']);
      expect(ack).toHaveBeenCalledWith({ success: true });
      expect(socket.eventsNamed('sync-document')).toEqual([
        { documentId: 'doc-1', state: expect.any(String) },
      ]);
      expect(socket.roomEventsNamed('user-joined')[0].payload).toMatchObject({
        userId: 'user-sock-1',
        displayName: 'Name sock-1',
        socketId: 'sock-1',
      });
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(manager.getDocumentCount()).toBe(1);
      expect(ioRoomEmits).toContainEqual({
        room: 'doc:doc-1',
        event: 'presence-update',
        payload: { documentId: 'doc-1', users: expect.any(Array), count: 1 },
      });
    });

    it('rehydrates the document from the persisted CRDT state', async () => {
      documentStore.getDocumentState.mockResolvedValueOnce(stateBufferFor('Hello'));
      const socket = await connect('sock-1');

      await join(socket, 'doc-1');

      expect(manager.getDocument('doc-1')?.getText('content').toString()).toBe('Hello');
    });

    it('creates the document only once for concurrent joins', async () => {
      const a = await connect('sock-a');
      const b = await connect('sock-b');

      await Promise.all([
        a.trigger('join-document', { documentId: 'doc-1' }, () => {}),
        b.trigger('join-document', { documentId: 'doc-1' }, () => {}),
      ]);

      expect(documentStore.getDocumentState).toHaveBeenCalledTimes(1);
      expect(manager.getDocumentCount()).toBe(1);
      expect(awareness.getDocumentUserCount('doc-1')).toBe(2);
    });

    it('reuses an already loaded document for a later joiner', async () => {
      const a = await connect('sock-a');
      await join(a, 'doc-1');
      const b = await connect('sock-b');

      await join(b, 'doc-1');

      expect(documentStore.getDocumentState).toHaveBeenCalledTimes(1);
    });

    it('leaves the previous document when a socket switches', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-old');

      await join(socket, 'doc-new');

      expect(socket.left).toEqual(['doc:doc-old']);
      expect(socket.roomEventsNamed('user-left')[0]).toMatchObject({
        room: 'doc:doc-old',
        payload: { socketId: 'sock-1', userId: 'user-sock-1' },
      });
      expect(awareness.getDocumentUserCount('doc-old')).toBe(0);
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-old',
        expect.any(Buffer),
      );
      expect(manager.getDocument('doc-old')).toBeUndefined();
    });

    it('does not tear the document down when another user stays behind', async () => {
      const a = await connect('sock-a');
      const b = await connect('sock-b');
      await join(a, 'doc-old');
      await join(b, 'doc-old');

      await join(a, 'doc-new');

      expect(manager.getDocument('doc-old')).toBeDefined();
      expect(awareness.getDocumentUserCount('doc-old')).toBe(1);
    });

    it('works without an acknowledgement callback', async () => {
      const socket = await connect('sock-1');

      await socket.trigger('join-document', { documentId: 'doc-1' });

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });

    it('reports a failed join and rolls the socket out of the room', async () => {
      const socket = await connect('sock-1');
      socket.joinError = new Error('room join rejected');
      const ack = jest.fn();

      await socket.trigger('join-document', { documentId: 'doc-1' }, ack);

      expect(ack).toHaveBeenCalledWith({
        success: false,
        error: 'Failed to join document',
      });
      expect(socket.left).toEqual(['doc:doc-1']);
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'join_document_failed',
      );
      expect(await metrics.getMetrics()).toContain(
        'collab_connection_errors_total{reason="join_failed"} 1',
      );
    });

    it('swallows a failed join with no acknowledgement callback', async () => {
      const socket = await connect('sock-1');
      socket.joinError = new Error('room join rejected');

      await expect(
        socket.trigger('join-document', { documentId: 'doc-1' }),
      ).resolves.toBeUndefined();
    });
  });

  describe('leave-document', () => {
    it('announces the departure and persists the emptied document', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      await socket.trigger('leave-document', { documentId: 'doc-1' });
      await Promise.resolve();

      expect(socket.left).toEqual(['doc:doc-1']);
      expect(socket.roomEventsNamed('user-left')).toHaveLength(1);
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
    });

    it('falls back to the client-supplied document id when untracked', async () => {
      const socket = await connect('sock-1');

      await socket.trigger('leave-document', { documentId: 'doc-untracked' });

      expect(socket.left).toEqual(['doc:doc-untracked']);
      expect(socket.roomEventsNamed('user-left')).toHaveLength(0);
    });

    it('keeps the document in memory while other users remain', async () => {
      const a = await connect('sock-a');
      const b = await connect('sock-b');
      await join(a, 'doc-1');
      await join(b, 'doc-1');

      await a.trigger('leave-document', { documentId: 'doc-1' });

      expect(manager.getDocument('doc-1')).toBeDefined();
      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });
  });

  describe('document-update', () => {
    it('applies, broadcasts and persists a CRDT update', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');
      const update = encodeUpdate('Hello');

      await socket.trigger('document-update', { documentId: 'doc-1', update });

      expect(manager.getDocument('doc-1')?.getText('content').toString()).toBe('Hello');
      expect(socket.roomEventsNamed('document-update')[0].payload).toEqual({
        documentId: 'doc-1',
        update,
      });
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'user-sock-1',
      );
      expect(await metrics.getMetrics()).toContain('collab_document_updates_total 1');
    });

    it('broadcasts non-string updates without touching the CRDT', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      await socket.trigger('document-update', {
        documentId: 'doc-1',
        update: { op: 'replace', value: 'x' },
      });

      expect(socket.roomEventsNamed('document-update')[0].payload).toEqual({
        documentId: 'doc-1',
        update: { op: 'replace', value: 'x' },
      });
    });

    it('ignores updates for a document that is not loaded', async () => {
      const socket = await connect('sock-1');

      await socket.trigger('document-update', {
        documentId: 'doc-unknown',
        update: encodeUpdate('Hi'),
      });

      expect(logger.warn).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-unknown' }),
        'document_update_for_unknown_doc',
      );
      expect(socket.roomEventsNamed('document-update')).toHaveLength(0);
    });

    it('reports an undecodable update back to the sender only', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      await socket.trigger('document-update', {
        documentId: 'doc-1',
        update: Buffer.from([255, 255, 255, 255]).toString('base64'),
      });

      expect(socket.eventsNamed('document-update-error')).toEqual([
        { documentId: 'doc-1', error: 'Failed to apply update' },
      ]);
      expect(socket.roomEventsNamed('document-update')).toHaveLength(0);
      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });

    it('still broadcasts when persistence fails', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await socket.trigger('document-update', {
        documentId: 'doc-1',
        update: encodeUpdate('Hello'),
      });

      expect(socket.roomEventsNamed('document-update')).toHaveLength(1);
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'document_persist_failed',
      );
      expect(await metrics.getMetrics()).toContain(
        'collab_persistence_operations_total{operation="save_state",status="error"} 1',
      );
    });

    it('refreshes the sender activity so an active editor is not evicted', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');
      jest.setSystemTime(new Date('2026-01-01T00:10:00Z'));

      await socket.trigger('document-update', {
        documentId: 'doc-1',
        update: encodeUpdate('Hello'),
      });

      expect(awareness.cleanupStaleUsers(300000)).toEqual([]);
    });
  });

  describe('cursor-update', () => {
    it('broadcasts the cursor with the user colour', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      socket.trigger('cursor-update', {
        documentId: 'doc-1',
        cursor: { index: 42, length: 0 },
        selection: null,
      });

      expect(socket.roomEventsNamed('cursor-update')[0].payload).toMatchObject({
        socketId: 'sock-1',
        userId: 'user-sock-1',
        cursor: { index: 42, length: 0 },
        selection: null,
      });
    });

    it('ignores a cursor from a socket that never joined', async () => {
      const socket = await connect('sock-1');

      socket.trigger('cursor-update', {
        documentId: 'doc-1',
        cursor: { index: 1, length: 0 },
        selection: null,
      });

      expect(socket.roomEventsNamed('cursor-update')).toHaveLength(0);
    });
  });

  describe('typing-indicator', () => {
    it('broadcasts the typing state of a joined user', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      socket.trigger('typing-indicator', { documentId: 'doc-1', isTyping: true });

      expect(socket.roomEventsNamed('typing-indicator')[0].payload).toEqual({
        socketId: 'sock-1',
        userId: 'user-sock-1',
        displayName: 'Name sock-1',
        isTyping: true,
      });
    });

    it('ignores typing from a socket that never joined', async () => {
      const socket = await connect('sock-1');

      socket.trigger('typing-indicator', { documentId: 'doc-1', isTyping: true });

      expect(socket.roomEventsNamed('typing-indicator')).toHaveLength(0);
    });
  });

  describe('comment annotations', () => {
    it('stamps an added comment with its author and echoes it to everyone', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      socket.trigger('comment-add', {
        documentId: 'doc-1',
        comment: {
          id: 'c-1',
          documentId: 'doc-1',
          threadId: 't-1',
          content: 'Looks good',
          rangeStart: 0,
          rangeEnd: 5,
        },
      });

      const expected = {
        id: 'c-1',
        documentId: 'doc-1',
        threadId: 't-1',
        content: 'Looks good',
        rangeStart: 0,
        rangeEnd: 5,
        author: { userId: 'user-sock-1', displayName: 'Name sock-1' },
        createdAt: '2026-01-01T00:00:00.000Z',
      };
      expect(socket.eventsNamed('comment-added')).toEqual([expected]);
      expect(socket.roomEventsNamed('comment-added')[0].payload).toEqual(expected);
    });

    it('broadcasts a comment edit to the room only', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      socket.trigger('comment-update', {
        documentId: 'doc-1',
        commentId: 'c-1',
        content: 'Edited',
      });

      expect(socket.roomEventsNamed('comment-updated')[0].payload).toEqual({
        commentId: 'c-1',
        content: 'Edited',
        updatedBy: { userId: 'user-sock-1', displayName: 'Name sock-1' },
        updatedAt: '2026-01-01T00:00:00.000Z',
      });
      expect(socket.eventsNamed('comment-updated')).toHaveLength(0);
    });

    it('broadcasts a comment deletion to the room', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      socket.trigger('comment-delete', { documentId: 'doc-1', commentId: 'c-1' });

      expect(socket.roomEventsNamed('comment-deleted')[0].payload).toEqual({
        commentId: 'c-1',
        deletedBy: 'user-sock-1',
      });
      expect(await metrics.getMetrics()).toContain(
        'collab_comment_annotations_total{action="delete"} 1',
      );
    });
  });

  describe('request-snapshot', () => {
    it('creates a labelled snapshot and shares it with the room', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      await socket.trigger('request-snapshot', {
        documentId: 'doc-1',
        label: 'before-review',
      });

      expect(documentStore.createSnapshot).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'user-sock-1',
        'before-review',
      );
      expect(socket.eventsNamed('snapshot-created')).toEqual([SNAPSHOT]);
      expect(socket.roomEventsNamed('snapshot-created')[0].payload).toEqual(SNAPSHOT);
    });

    it('rejects a snapshot request for a document that is not loaded', async () => {
      const socket = await connect('sock-1');

      await socket.trigger('request-snapshot', { documentId: 'doc-unknown' });

      expect(socket.eventsNamed('snapshot-error')).toEqual([
        { documentId: 'doc-unknown', error: 'Document not found' },
      ]);
      expect(documentStore.createSnapshot).not.toHaveBeenCalled();
    });

    it('reports a snapshot store failure to the requester', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');
      documentStore.createSnapshot.mockRejectedValueOnce(new Error('redis down'));

      await socket.trigger('request-snapshot', { documentId: 'doc-1' });

      expect(socket.eventsNamed('snapshot-error')).toEqual([
        { documentId: 'doc-1', error: 'Failed to create snapshot' },
      ]);
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'create_snapshot_failed',
      );
    });
  });

  describe('request-history', () => {
    it('returns snapshots using the default limit', async () => {
      const socket = await connect('sock-1');

      await socket.trigger('request-history', { documentId: 'doc-1' });

      expect(documentStore.getSnapshots).toHaveBeenCalledWith('doc-1', 20);
      expect(socket.eventsNamed('document-history')).toEqual([
        { documentId: 'doc-1', snapshots: [SNAPSHOT] },
      ]);
    });

    it('honours an explicit limit', async () => {
      const socket = await connect('sock-1');

      await socket.trigger('request-history', { documentId: 'doc-1', limit: 5 });

      expect(documentStore.getSnapshots).toHaveBeenCalledWith('doc-1', 5);
    });

    it('reports a history lookup failure', async () => {
      const socket = await connect('sock-1');
      documentStore.getSnapshots.mockRejectedValueOnce(new Error('redis down'));

      await socket.trigger('request-history', { documentId: 'doc-1' });

      expect(socket.eventsNamed('history-error')).toEqual([
        { documentId: 'doc-1', error: 'Failed to retrieve history' },
      ]);
    });
  });

  describe('disconnect', () => {
    it('removes the user, notifies the room and persists the empty document', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      socket.trigger('disconnect', 'transport close');
      await Promise.resolve();

      expect(socket.roomEventsNamed('user-left')[0].payload).toEqual({
        socketId: 'sock-1',
        userId: 'user-sock-1',
      });
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
      expect(await metrics.getMetrics()).toContain('collab_active_connections 0');
    });

    it('only decrements the connection gauge when the socket never joined', async () => {
      const socket = await connect('sock-1');

      socket.trigger('disconnect', 'client namespace disconnect');

      expect(socket.roomEventsNamed('user-left')).toHaveLength(0);
      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });
  });

  describe('persistAndCleanupDocument', () => {
    it('is a no-op for a document that is not in memory', async () => {
      await manager.persistAndCleanupDocument('doc-unknown');

      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });

    it('persists once when two cleanups race for the same document', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      await Promise.all([
        manager.persistAndCleanupDocument('doc-1'),
        manager.persistAndCleanupDocument('doc-1'),
      ]);

      expect(documentStore.saveDocumentState).toHaveBeenCalledTimes(1);
    });

    it('keeps the document when a user re-joined during persistence', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');
      awareness.removeUser('sock-1');
      documentStore.saveDocumentState.mockImplementationOnce(async () => {
        awareness.addUser('doc-1', 'sock-late', 'user-late', 'Late', 'l@test.com');
      });

      await manager.persistAndCleanupDocument('doc-1');

      expect(manager.getDocument('doc-1')).toBeDefined();
    });

    it('keeps the document in memory when persistence fails', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');
      awareness.removeUser('sock-1');
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await manager.persistAndCleanupDocument('doc-1');

      expect(manager.getDocument('doc-1')).toBeDefined();
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'document_persist_on_cleanup_failed',
      );
    });
  });

  describe('background loops', () => {
    it('persists every loaded document on the persistence interval', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      await jest.advanceTimersByTimeAsync(30000);

      expect(documentStore.saveDocumentState).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
      );
      expect(await metrics.getMetrics()).toContain(
        'collab_persistence_operations_total{operation="periodic_save",status="success"} 1',
      );
    });

    it('records a failed periodic persistence without stopping the loop', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');
      documentStore.saveDocumentState.mockRejectedValueOnce(new Error('redis down'));

      await jest.advanceTimersByTimeAsync(60000);

      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'periodic_persistence_failed',
      );
      expect(await metrics.getMetrics()).toContain(
        'collab_persistence_operations_total{operation="periodic_save",status="error"} 1',
      );
    });

    it('takes an automatic snapshot on the snapshot interval', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      await jest.advanceTimersByTimeAsync(300000);

      expect(documentStore.createSnapshot).toHaveBeenCalledWith(
        'doc-1',
        expect.any(Buffer),
        'system',
        'auto-snapshot',
      );
    });

    it('logs a failed automatic snapshot', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');
      documentStore.createSnapshot.mockRejectedValueOnce(new Error('redis down'));

      await jest.advanceTimersByTimeAsync(300000);

      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
        'periodic_snapshot_failed',
      );
    });
  });

  describe('stop', () => {
    it('flushes every document and stops the timers', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');

      await manager.stop();
      documentStore.saveDocumentState.mockClear();
      await jest.advanceTimersByTimeAsync(600000);

      expect(logger.info).toHaveBeenCalledWith(
        { documentId: 'doc-1' },
        'document_persisted_on_shutdown',
      );
      expect(documentStore.saveDocumentState).not.toHaveBeenCalled();
    });

    it('logs a shutdown flush failure and still completes', async () => {
      const socket = await connect('sock-1');
      await join(socket, 'doc-1');
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
    const io = {
      on: jest.fn(),
      to: () => ({ emit: jest.fn() }),
      sockets: { sockets: new Map() },
    } as unknown as SocketIOServer;
    const documentStore = {
      getDocumentState: jest.fn().mockResolvedValue(null),
      saveDocumentState: jest.fn().mockResolvedValue(undefined),
    } as unknown as DocumentStore;
    const awareness = new AwarenessService(logger);
    const metrics = new MetricsCollector();

    const manager = setupCollaborationHandlers(
      io,
      documentStore,
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
