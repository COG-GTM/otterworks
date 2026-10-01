import type { Server as SocketIOServer } from 'socket.io';
import { PresenceHandler } from '../handlers/presence';
import { AwarenessService } from '../services/awareness';

const logger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

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

function createFakeIo(sockets: Map<string, FakeSocket>) {
  const roomEmit = jest.fn();
  const io = {
    to: jest.fn(() => ({ emit: roomEmit })),
    sockets: { sockets },
  };
  return { io: io as unknown as SocketIOServer, ioTo: io.to, roomEmit };
}

describe('PresenceHandler', () => {
  let awareness: AwarenessService;
  let handler: PresenceHandler;
  let timer: NodeJS.Timeout | null;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    awareness = new AwarenessService(logger);
    handler = new PresenceHandler(awareness, logger);
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
    it('returns nothing when no document has users', () => {
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
      const { io, ioTo, roomEmit } = createFakeIo(new Map());

      handler.broadcastPresenceUpdate(io, 'doc-1');

      expect(ioTo).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
    });
  });

  describe('startCleanupInterval', () => {
    it('evicts idle users, notifies their socket and the room, and rebroadcasts', () => {
      const staleSocket = createFakeSocket();
      const sockets = new Map<string, FakeSocket>([['sock-a', staleSocket]]);
      const { io, roomEmit } = createFakeIo(sockets);
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');

      timer = handler.startCleanupInterval(io, 60000, 300000);
      jest.advanceTimersByTime(360000);

      expect(staleSocket.emit).toHaveBeenCalledWith('session-expired', {
        documentId: 'doc-1',
        reason: 'idle_timeout',
      });
      expect(staleSocket.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(staleSocket.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 'sock-a',
        userId: 'user-a',
      });
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('still rebroadcasts when the evicted socket is already gone', () => {
      const { io, roomEmit } = createFakeIo(new Map());
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');

      timer = handler.startCleanupInterval(io, 60000, 300000);
      jest.advanceTimersByTime(360000);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
    });

    it('invokes the empty-document callback once per emptied document', () => {
      const { io } = createFakeIo(new Map());
      const onDocumentEmpty = jest.fn();
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
      awareness.addUser('doc-2', 'sock-b', 'user-b', 'Bob', 'b@test.com');

      timer = handler.startCleanupInterval(io, 60000, 300000, onDocumentEmpty);
      jest.advanceTimersByTime(360000);

      expect(onDocumentEmpty.mock.calls.map(([id]) => id).sort()).toEqual([
        'doc-1',
        'doc-2',
      ]);
    });

    it('leaves active users alone and never broadcasts when nothing expires', () => {
      const { io, roomEmit } = createFakeIo(new Map());
      const onDocumentEmpty = jest.fn();
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');

      timer = handler.startCleanupInterval(io, 60000, 300000, onDocumentEmpty);
      jest.advanceTimersByTime(120000);

      expect(roomEmit).not.toHaveBeenCalled();
      expect(onDocumentEmpty).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });

    it('uses the documented default interval and idle window', () => {
      const { io, roomEmit } = createFakeIo(new Map());
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');

      timer = handler.startCleanupInterval(io);
      jest.advanceTimersByTime(299000);
      expect(roomEmit).not.toHaveBeenCalled();

      jest.advanceTimersByTime(120000);
      expect(roomEmit).toHaveBeenCalled();
    });
  });
});
