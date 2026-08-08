import type { Logger } from 'pino';
import type { Server as SocketIOServer } from 'socket.io';
import { PresenceHandler } from '../handlers/presence';
import { AwarenessService } from '../services/awareness';

function createLoggerMock() {
  return {
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
    debug: jest.fn(),
  };
}

interface SocketStub {
  emit: jest.Mock;
  leave: jest.Mock;
  to: jest.Mock;
  roomEmit: jest.Mock;
}

function createSocketStub(): SocketStub {
  const roomEmit = jest.fn();
  return {
    emit: jest.fn(),
    leave: jest.fn(),
    to: jest.fn(() => ({ emit: roomEmit })),
    roomEmit,
  };
}

function createIoStub(sockets: Map<string, SocketStub>) {
  const roomEmit = jest.fn();
  const io = {
    to: jest.fn(() => ({ emit: roomEmit })),
    sockets: { sockets },
  };
  return { io: io as unknown as SocketIOServer, toRoom: io.to, roomEmit };
}

describe('PresenceHandler', () => {
  let logger: ReturnType<typeof createLoggerMock>;
  let awareness: AwarenessService;
  let handler: PresenceHandler;

  beforeEach(() => {
    jest.clearAllMocks();
    logger = createLoggerMock();
    awareness = new AwarenessService(logger as unknown as Logger);
    handler = new PresenceHandler(awareness, logger as unknown as Logger);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('getDocumentPresence', () => {
    it('reports an empty roster for an unknown document', () => {
      expect(handler.getDocumentPresence('doc-missing')).toEqual({
        documentId: 'doc-missing',
        users: [],
        count: 0,
      });
    });

    it('reports every user currently in the document', () => {
      awareness.addUser('doc-1', 'socket-a', 'user-a', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 'socket-b', 'user-b', 'Bob', 'b@test.com');

      const presence = handler.getDocumentPresence('doc-1');

      expect(presence.documentId).toBe('doc-1');
      expect(presence.count).toBe(2);
      expect(presence.users.map((u) => u.userId)).toEqual(['user-a', 'user-b']);
    });
  });

  describe('getActiveDocuments', () => {
    it('returns an empty list when nothing is active', () => {
      expect(handler.getActiveDocuments()).toEqual([]);
    });

    it('returns per-document user counts', () => {
      awareness.addUser('doc-1', 'socket-a', 'user-a', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 'socket-b', 'user-b', 'Bob', 'b@test.com');
      awareness.addUser('doc-2', 'socket-c', 'user-c', 'Carol', 'c@test.com');

      expect(handler.getActiveDocuments()).toEqual([
        { documentId: 'doc-1', userCount: 2 },
        { documentId: 'doc-2', userCount: 1 },
      ]);
    });
  });

  it('broadcasts presence to the document room', () => {
    awareness.addUser('doc-1', 'socket-a', 'user-a', 'Alice', 'a@test.com');
    const { io, toRoom, roomEmit } = createIoStub(new Map());

    handler.broadcastPresenceUpdate(io, 'doc-1');

    expect(toRoom).toHaveBeenCalledWith('doc:doc-1');
    expect(roomEmit).toHaveBeenCalledWith('presence-update', {
      documentId: 'doc-1',
      users: expect.arrayContaining([expect.objectContaining({ userId: 'user-a' })]),
      count: 1,
    });
  });

  describe('startCleanupInterval', () => {
    it('evicts stale users, notifies their socket and broadcasts the new presence', () => {
      jest.useFakeTimers().setSystemTime(new Date('2026-01-01T00:00:00Z'));
      awareness.addUser('doc-1', 'socket-a', 'user-a', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 'socket-b', 'user-b', 'Bob', 'b@test.com');
      const staleSocket = createSocketStub();
      const { io, roomEmit } = createIoStub(
        new Map([['socket-a', staleSocket]]) as never,
      );
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 1000, 5000, onDocumentEmpty);
      jest.setSystemTime(new Date('2026-01-01T00:00:04Z'));
      jest.advanceTimersByTime(1000);

      expect(staleSocket.emit).not.toHaveBeenCalled();

      jest.setSystemTime(new Date('2026-01-01T00:00:20Z'));
      jest.advanceTimersByTime(1000);

      expect(staleSocket.emit).toHaveBeenCalledWith('session-expired', {
        documentId: 'doc-1',
        reason: 'idle_timeout',
      });
      expect(staleSocket.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(staleSocket.to).toHaveBeenCalledWith('doc:doc-1');
      expect(staleSocket.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 'socket-a',
        userId: 'user-a',
      });
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');

      clearInterval(timer);
    });

    it('tolerates evicted sockets that are already gone and no empty-document callback', () => {
      jest.useFakeTimers().setSystemTime(new Date('2026-01-01T00:00:00Z'));
      awareness.addUser('doc-1', 'socket-a', 'user-a', 'Alice', 'a@test.com');
      const { io, roomEmit } = createIoStub(new Map());

      const timer = handler.startCleanupInterval(io, 1000, 5000);
      jest.setSystemTime(new Date('2026-01-01T00:00:20Z'));
      jest.advanceTimersByTime(1000);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(logger.info).toHaveBeenCalledWith(
        { documentId: 'doc-1', userId: 'user-a' },
        'stale_user_removed_from_presence',
      );

      clearInterval(timer);
    });

    it('does nothing while every user is active', () => {
      jest.useFakeTimers().setSystemTime(new Date('2026-01-01T00:00:00Z'));
      awareness.addUser('doc-1', 'socket-a', 'user-a', 'Alice', 'a@test.com');
      const { io, roomEmit } = createIoStub(new Map());

      const timer = handler.startCleanupInterval(io);
      jest.advanceTimersByTime(60000);

      expect(roomEmit).not.toHaveBeenCalled();

      clearInterval(timer);
    });
  });
});
