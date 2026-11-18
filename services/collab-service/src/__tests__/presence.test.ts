import type { Server as SocketIOServer } from 'socket.io';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

function fakeSocket() {
  const toEmit = jest.fn();
  return {
    emit: jest.fn(),
    leave: jest.fn(),
    to: jest.fn(() => ({ emit: toEmit })),
    toEmit,
  };
}

function fakeIo(sockets: Record<string, ReturnType<typeof fakeSocket>> = {}) {
  const roomEmit = jest.fn();
  const io = {
    to: jest.fn(() => ({ emit: roomEmit })),
    sockets: { sockets: new Map(Object.entries(sockets)) },
  };
  return { io: io as unknown as SocketIOServer, raw: io, roomEmit };
}

describe('PresenceHandler', () => {
  let awareness: AwarenessService;
  let handler: PresenceHandler;

  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    awareness = new AwarenessService(mockLogger);
    handler = new PresenceHandler(awareness, mockLogger);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('getDocumentPresence returns users and count', () => {
    awareness.addUser('d1', 's1', 'u1', 'A', 'a@x');
    awareness.addUser('d1', 's2', 'u2', 'B', 'b@x');
    const presence = handler.getDocumentPresence('d1');
    expect(presence.documentId).toBe('d1');
    expect(presence.count).toBe(2);
    expect(presence.users.map((u) => u.userId).sort()).toEqual(['u1', 'u2']);
    expect(handler.getDocumentPresence('nope')).toEqual({
      documentId: 'nope',
      users: [],
      count: 0,
    });
  });

  it('getActiveDocuments lists documents with user counts', () => {
    expect(handler.getActiveDocuments()).toEqual([]);
    awareness.addUser('d1', 's1', 'u1', 'A', 'a@x');
    awareness.addUser('d1', 's2', 'u2', 'B', 'b@x');
    awareness.addUser('d2', 's3', 'u3', 'C', 'c@x');
    expect(handler.getActiveDocuments()).toEqual([
      { documentId: 'd1', userCount: 2 },
      { documentId: 'd2', userCount: 1 },
    ]);
  });

  it('broadcastPresenceUpdate emits presence-update to the document room', () => {
    const { io, raw, roomEmit } = fakeIo();
    awareness.addUser('d1', 's1', 'u1', 'A', 'a@x');
    handler.broadcastPresenceUpdate(io, 'd1');
    expect(raw.to).toHaveBeenCalledWith('doc:d1');
    expect(roomEmit).toHaveBeenCalledWith(
      'presence-update',
      expect.objectContaining({ documentId: 'd1', count: 1 }),
    );
  });

  describe('startCleanupInterval', () => {
    it('evicts stale users, notifies them and triggers onDocumentEmpty', () => {
      const s1 = fakeSocket();
      const { io, raw, roomEmit } = fakeIo({ s1 });
      const onEmpty = jest.fn();
      awareness.addUser('d1', 's1', 'u1', 'A', 'a@x');

      const timer = handler.startCleanupInterval(io, 1000, 5000, onEmpty);
      jest.advanceTimersByTime(1000);
      expect(s1.emit).not.toHaveBeenCalled();

      jest.advanceTimersByTime(5000);
      expect(s1.emit).toHaveBeenCalledWith('session-expired', {
        documentId: 'd1',
        reason: 'idle_timeout',
      });
      expect(s1.leave).toHaveBeenCalledWith('doc:d1');
      expect(s1.to).toHaveBeenCalledWith('doc:d1');
      expect(s1.toEmit).toHaveBeenCalledWith('user-left', {
        socketId: 's1',
        userId: 'u1',
      });
      expect(raw.to).toHaveBeenCalledWith('doc:d1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'd1', count: 0 }),
      );
      expect(onEmpty).toHaveBeenCalledTimes(1);
      expect(onEmpty).toHaveBeenCalledWith('d1');
      expect(awareness.getDocumentUserCount('d1')).toBe(0);
      clearInterval(timer);
    });

    it('handles evicted sockets that are no longer connected', () => {
      const { io, roomEmit } = fakeIo();
      const onEmpty = jest.fn();
      awareness.addUser('d1', 'gone', 'u1', 'A', 'a@x');

      const timer = handler.startCleanupInterval(io, 1000, 500, onEmpty);
      jest.advanceTimersByTime(1000);
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'd1' }),
      );
      expect(onEmpty).toHaveBeenCalledWith('d1');
      clearInterval(timer);
    });

    it('does not trigger onDocumentEmpty while active users remain', () => {
      const { io } = fakeIo();
      const onEmpty = jest.fn();
      awareness.addUser('d1', 'stale', 'u1', 'A', 'a@x');
      jest.advanceTimersByTime(3000);
      awareness.addUser('d1', 'fresh', 'u2', 'B', 'b@x');

      const timer = handler.startCleanupInterval(io, 1000, 2500, onEmpty);
      jest.advanceTimersByTime(1000);
      expect(awareness.getDocumentUserCount('d1')).toBe(1);
      expect(onEmpty).not.toHaveBeenCalled();
      clearInterval(timer);
    });

    it('works without an onDocumentEmpty callback and uses default timings', () => {
      const s1 = fakeSocket();
      const { io } = fakeIo({ s1 });
      awareness.addUser('d1', 's1', 'u1', 'A', 'a@x');

      const timer = handler.startCleanupInterval(io);
      jest.advanceTimersByTime(60000 * 5);
      expect(s1.emit).not.toHaveBeenCalled();
      jest.advanceTimersByTime(60000);
      expect(s1.emit).toHaveBeenCalledWith('session-expired', expect.anything());
      clearInterval(timer);
    });

    it('does nothing when no users are stale', () => {
      const { io, roomEmit } = fakeIo();
      awareness.addUser('d1', 's1', 'u1', 'A', 'a@x');
      const timer = handler.startCleanupInterval(io, 1000, 60000, jest.fn());
      jest.advanceTimersByTime(3000);
      expect(roomEmit).not.toHaveBeenCalled();
      clearInterval(timer);
    });
  });
});
