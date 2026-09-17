import type { Logger } from 'pino';
import type { Server as SocketIOServer } from 'socket.io';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';

interface RoomEmit {
  room: string;
  event: string;
  payload: unknown;
}

interface FakeSocket {
  id: string;
  emitted: Array<{ event: string; payload: unknown }>;
  left: string[];
  roomEmits: RoomEmit[];
  emit: (event: string, payload: unknown) => void;
  leave: (room: string) => void;
  to: (room: string) => { emit: (event: string, payload: unknown) => void };
}

function createFakeSocket(id: string): FakeSocket {
  const socket: FakeSocket = {
    id,
    emitted: [],
    left: [],
    roomEmits: [],
    emit: (event, payload) => {
      socket.emitted.push({ event, payload });
    },
    leave: (room) => {
      socket.left.push(room);
    },
    to: (room) => ({
      emit: (event, payload) => socket.roomEmits.push({ room, event, payload }),
    }),
  };
  return socket;
}

function createFakeIo(sockets: Map<string, FakeSocket>) {
  const roomEmits: RoomEmit[] = [];
  const io = {
    to: (room: string) => ({
      emit: (event: string, payload: unknown) => roomEmits.push({ room, event, payload }),
    }),
    sockets: { sockets },
  };
  return { io: io as unknown as SocketIOServer, roomEmits };
}

const logger = {
  info: jest.fn(),
  debug: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
} as unknown as Logger;

describe('PresenceHandler', () => {
  let awareness: AwarenessService;
  let handler: PresenceHandler;
  let sockets: Map<string, FakeSocket>;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    awareness = new AwarenessService(logger);
    handler = new PresenceHandler(awareness, logger);
    sockets = new Map();
  });

  afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
  });

  describe('getDocumentPresence', () => {
    it('reports every user currently in the document', () => {
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 'sock-b', 'user-b', 'Bob', 'b@test.com');

      const presence = handler.getDocumentPresence('doc-1');

      expect(presence.documentId).toBe('doc-1');
      expect(presence.count).toBe(2);
      expect(presence.users.map((u) => u.userId)).toEqual(['user-a', 'user-b']);
    });

    it('reports an empty document as zero users', () => {
      expect(handler.getDocumentPresence('doc-unknown')).toEqual({
        documentId: 'doc-unknown',
        users: [],
        count: 0,
      });
    });
  });

  describe('getActiveDocuments', () => {
    it('lists each active document with its user count', () => {
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 'sock-b', 'user-b', 'Bob', 'b@test.com');
      awareness.addUser('doc-2', 'sock-c', 'user-c', 'Carol', 'c@test.com');

      expect(handler.getActiveDocuments()).toEqual([
        { documentId: 'doc-1', userCount: 2 },
        { documentId: 'doc-2', userCount: 1 },
      ]);
    });

    it('is empty when nobody is connected', () => {
      expect(handler.getActiveDocuments()).toEqual([]);
    });
  });

  describe('broadcastPresenceUpdate', () => {
    it('emits the presence snapshot to the document room', () => {
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
      const { io, roomEmits } = createFakeIo(sockets);

      handler.broadcastPresenceUpdate(io, 'doc-1');

      expect(roomEmits).toEqual([
        {
          room: 'doc:doc-1',
          event: 'presence-update',
          payload: { documentId: 'doc-1', users: expect.any(Array), count: 1 },
        },
      ]);
    });
  });

  describe('startCleanupInterval', () => {
    it('evicts idle users, notifies them and rebroadcasts presence', () => {
      const socket = createFakeSocket('sock-idle');
      sockets.set('sock-idle', socket);
      awareness.addUser('doc-1', 'sock-idle', 'user-a', 'Alice', 'a@test.com');
      const { io, roomEmits } = createFakeIo(sockets);

      const timer = handler.startCleanupInterval(io, 60000, 300000);
      jest.advanceTimersByTime(400000);

      expect(socket.emitted).toEqual([
        {
          event: 'session-expired',
          payload: { documentId: 'doc-1', reason: 'idle_timeout' },
        },
      ]);
      expect(socket.left).toEqual(['doc:doc-1']);
      expect(socket.roomEmits).toEqual([
        {
          room: 'doc:doc-1',
          event: 'user-left',
          payload: { socketId: 'sock-idle', userId: 'user-a' },
        },
      ]);
      expect(roomEmits[0]).toMatchObject({
        room: 'doc:doc-1',
        event: 'presence-update',
        payload: { count: 0 },
      });
      clearInterval(timer);
    });

    it('invokes the empty-document callback once the last user is evicted', () => {
      sockets.set('sock-idle', createFakeSocket('sock-idle'));
      awareness.addUser('doc-1', 'sock-idle', 'user-a', 'Alice', 'a@test.com');
      const onDocumentEmpty = jest.fn();
      const { io } = createFakeIo(sockets);

      const timer = handler.startCleanupInterval(io, 60000, 300000, onDocumentEmpty);
      jest.advanceTimersByTime(400000);

      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      clearInterval(timer);
    });

    it('does not fire the empty-document callback while users remain', () => {
      sockets.set('sock-idle', createFakeSocket('sock-idle'));
      awareness.addUser('doc-1', 'sock-idle', 'user-a', 'Alice', 'a@test.com');
      const onDocumentEmpty = jest.fn();
      const { io } = createFakeIo(sockets);

      const timer = handler.startCleanupInterval(io, 60000, 300000, onDocumentEmpty);
      jest.advanceTimersByTime(200000);
      awareness.addUser('doc-1', 'sock-active', 'user-b', 'Bob', 'b@test.com');
      jest.advanceTimersByTime(200000);

      expect(onDocumentEmpty).not.toHaveBeenCalled();
      clearInterval(timer);
    });

    it('still evicts awareness entries whose socket has already gone away', () => {
      awareness.addUser('doc-1', 'sock-gone', 'user-a', 'Alice', 'a@test.com');
      const { io, roomEmits } = createFakeIo(sockets);

      const timer = handler.startCleanupInterval(io, 60000, 300000);
      jest.advanceTimersByTime(400000);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
      expect(roomEmits).toHaveLength(1);
      clearInterval(timer);
    });

    it('does nothing while every user is active', () => {
      awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
      const { io, roomEmits } = createFakeIo(sockets);

      const timer = handler.startCleanupInterval(io);
      jest.advanceTimersByTime(120000);

      expect(roomEmits).toEqual([]);
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      clearInterval(timer);
    });
  });
});
