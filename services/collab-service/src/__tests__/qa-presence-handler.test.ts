import type { Server as SocketIOServer } from 'socket.io';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';
import { createMockLogger } from './qa-test-helpers';

function fakeIo() {
  const roomEmit = jest.fn();
  const sockets = new Map<string, unknown>();
  const io = {
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    sockets: { sockets },
  };
  return { io: io as unknown as SocketIOServer, roomEmit, sockets, raw: io };
}

describe('QA: PresenceHandler', () => {
  let awareness: AwarenessService;
  let presence: PresenceHandler;

  beforeEach(() => {
    awareness = new AwarenessService(createMockLogger());
    presence = new PresenceHandler(awareness, createMockLogger());
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('reports empty presence for unknown documents', () => {
    expect(presence.getDocumentPresence('nope')).toEqual({
      documentId: 'nope',
      users: [],
      count: 0,
    });
  });

  it('counts sockets (tabs) per document, not distinct users', () => {
    awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@x');
    awareness.addUser('doc-1', 's2', 'u1', 'Alice', 'a@x');
    awareness.addUser('doc-1', 's3', 'u2', 'Bob', 'b@x');
    const info = presence.getDocumentPresence('doc-1');
    expect(info.count).toBe(3);
    expect(info.users.map((u) => u.userId).sort()).toEqual(['u1', 'u1', 'u2']);
  });

  it('lists active documents with user counts', () => {
    awareness.addUser('doc-1', 's1', 'u1', 'A', '');
    awareness.addUser('doc-2', 's2', 'u2', 'B', '');
    awareness.addUser('doc-2', 's3', 'u3', 'C', '');
    expect(presence.getActiveDocuments()).toEqual(
      expect.arrayContaining([
        { documentId: 'doc-1', userCount: 1 },
        { documentId: 'doc-2', userCount: 2 },
      ]),
    );
  });

  it('broadcasts presence-update to the doc room', () => {
    const { io, roomEmit, raw } = fakeIo();
    awareness.addUser('doc-9', 's1', 'u1', 'A', '');
    presence.broadcastPresenceUpdate(io, 'doc-9');
    expect(raw.to).toHaveBeenCalledWith('doc:doc-9');
    expect(roomEmit).toHaveBeenCalledWith(
      'presence-update',
      expect.objectContaining({ documentId: 'doc-9', count: 1 }),
    );
  });

  it('cleanup interval evicts idle users, notifies the socket and fires onDocumentEmpty', () => {
    jest.useFakeTimers();
    const { io, roomEmit, sockets } = fakeIo();
    const evictedEmit = jest.fn();
    const leave = jest.fn();
    const roomBroadcast = jest.fn();
    sockets.set('s-idle', {
      emit: evictedEmit,
      leave,
      to: jest.fn().mockReturnValue({ emit: roomBroadcast }),
    });
    awareness.addUser('doc-idle', 's-idle', 'u-idle', 'Idle', '');
    const onEmpty = jest.fn();

    const timer = presence.startCleanupInterval(io, 1000, 500, onEmpty);
    jest.advanceTimersByTime(1001);
    clearInterval(timer);

    expect(evictedEmit).toHaveBeenCalledWith('session-expired', {
      documentId: 'doc-idle',
      reason: 'idle_timeout',
    });
    expect(leave).toHaveBeenCalledWith('doc:doc-idle');
    expect(roomBroadcast).toHaveBeenCalledWith('user-left', {
      socketId: 's-idle',
      userId: 'u-idle',
    });
    expect(roomEmit).toHaveBeenCalledWith(
      'presence-update',
      expect.objectContaining({ count: 0 }),
    );
    expect(onEmpty).toHaveBeenCalledWith('doc-idle');
    expect(awareness.getUserDocument('s-idle')).toBeNull();
  });

  it('cleanup interval keeps recently active users and does not fire onDocumentEmpty', () => {
    jest.useFakeTimers();
    const { io } = fakeIo();
    awareness.addUser('doc-live', 's1', 'u1', 'A', '');
    const onEmpty = jest.fn();
    const timer = presence.startCleanupInterval(io, 1000, 60_000, onEmpty);
    jest.advanceTimersByTime(1001);
    clearInterval(timer);
    expect(onEmpty).not.toHaveBeenCalled();
    expect(awareness.getDocumentUserCount('doc-live')).toBe(1);
  });

  it('cleanup tolerates evicted sockets that already disconnected', () => {
    jest.useFakeTimers();
    const { io, roomEmit } = fakeIo();
    awareness.addUser('doc-gone', 'ghost', 'u', 'G', '');
    const timer = presence.startCleanupInterval(io, 1000, 10);
    jest.advanceTimersByTime(1001);
    clearInterval(timer);
    expect(roomEmit).toHaveBeenCalledWith(
      'presence-update',
      expect.objectContaining({ count: 0 }),
    );
  });
});
