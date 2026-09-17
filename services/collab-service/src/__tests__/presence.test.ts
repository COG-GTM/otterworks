import type { Logger } from 'pino';
import type { Server as SocketIOServer } from 'socket.io';
import { PresenceHandler } from '../handlers/presence';
import { AwarenessService } from '../services/awareness';

interface FakeSocket {
  emit: jest.Mock;
  leave: jest.Mock;
  to: jest.Mock;
  roomEmit: jest.Mock;
}

function createFakeSocket(): FakeSocket {
  const roomEmit = jest.fn();
  return {
    emit: jest.fn(),
    leave: jest.fn(),
    to: jest.fn(() => ({ emit: roomEmit })),
    roomEmit,
  };
}

interface FakeIo {
  server: SocketIOServer;
  emit: jest.Mock;
  to: jest.Mock;
  sockets: Map<string, FakeSocket>;
}

function createFakeIo(): FakeIo {
  const emit = jest.fn();
  const to = jest.fn(() => ({ emit }));
  const sockets = new Map<string, FakeSocket>();
  const server = {
    to,
    sockets: { sockets },
  } as unknown as SocketIOServer;
  return { server, emit, to, sockets };
}

const logger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as unknown as Logger;

describe('PresenceHandler', () => {
  let awareness: AwarenessService;
  let handler: PresenceHandler;
  let io: FakeIo;
  let timer: NodeJS.Timeout | null;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    awareness = new AwarenessService(logger);
    handler = new PresenceHandler(awareness, logger);
    io = createFakeIo();
    timer = null;
  });

  afterEach(() => {
    if (timer) clearInterval(timer);
    jest.useRealTimers();
  });

  describe('getDocumentPresence', () => {
    it('reports an empty roster for an unknown document', () => {
      expect(handler.getDocumentPresence('doc-unknown')).toEqual({
        documentId: 'doc-unknown',
        users: [],
        count: 0,
      });
    });

    it('reports every user currently in the document', () => {
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 'sock-b', 'user-b', 'Bob', 'b@test.com');

      const presence = handler.getDocumentPresence('doc-1');

      expect(presence.count).toBe(2);
      expect(presence.users.map((u) => u.displayName)).toEqual(['Alice', 'Bob']);
    });
  });

  describe('getActiveDocuments', () => {
    it('returns an empty list when nobody is connected', () => {
      expect(handler.getActiveDocuments()).toEqual([]);
    });

    it('returns each active document with its user count', () => {
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 'sock-b', 'user-b', 'Bob', 'b@test.com');
      awareness.addUser('doc-2', 'sock-c', 'user-c', 'Carol', 'c@test.com');

      expect(handler.getActiveDocuments()).toEqual([
        { documentId: 'doc-1', userCount: 2 },
        { documentId: 'doc-2', userCount: 1 },
      ]);
    });
  });

  describe('broadcastPresenceUpdate', () => {
    it('emits the roster to the document room', () => {
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');

      handler.broadcastPresenceUpdate(io.server, 'doc-1');

      expect(io.to).toHaveBeenCalledWith('doc:doc-1');
      expect(io.emit).toHaveBeenCalledWith('presence-update', {
        documentId: 'doc-1',
        users: expect.arrayContaining([expect.objectContaining({ userId: 'user-a' })]),
        count: 1,
      });
    });
  });

  describe('startCleanupInterval', () => {
    it('does nothing while every user is active', () => {
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
      timer = handler.startCleanupInterval(io.server, 1000, 300000);

      jest.advanceTimersByTime(1000);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(io.emit).not.toHaveBeenCalled();
    });

    it('evicts idle users, notifies their socket and broadcasts the new roster', () => {
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 'sock-b', 'user-b', 'Bob', 'b@test.com');
      const evicted = createFakeSocket();
      io.sockets.set('sock-a', evicted);
      const onDocumentEmpty = jest.fn();
      timer = handler.startCleanupInterval(io.server, 60000, 1000, onDocumentEmpty);

      // Keep Bob active so only Alice's socket goes stale.
      jest.advanceTimersByTime(59000);
      awareness.refreshActivity('sock-b');
      jest.advanceTimersByTime(1000);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(evicted.emit).toHaveBeenCalledWith('session-expired', {
        documentId: 'doc-1',
        reason: 'idle_timeout',
      });
      expect(evicted.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(evicted.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 'sock-a',
        userId: 'user-a',
      });
      expect(io.emit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('reports the document as empty once its last user is evicted', () => {
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
      const onDocumentEmpty = jest.fn();
      timer = handler.startCleanupInterval(io.server, 60000, 1000, onDocumentEmpty);

      jest.advanceTimersByTime(60000);

      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('still evicts users whose socket is no longer registered on the server', () => {
      awareness.addUser('doc-1', 'sock-gone', 'user-a', 'Alice', 'a@test.com');
      timer = handler.startCleanupInterval(io.server, 60000, 1000);

      jest.advanceTimersByTime(60000);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
      expect(io.emit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
    });

    it('uses the documented defaults for interval and idle timeout', () => {
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
      timer = handler.startCleanupInterval(io.server);

      jest.advanceTimersByTime(60000);
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);

      jest.advanceTimersByTime(300000);
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });
  });
});
