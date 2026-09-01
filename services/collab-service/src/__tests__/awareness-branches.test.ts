import type { Logger } from 'pino';
import { AwarenessService } from '../services/awareness';

function createLoggerMock() {
  return {
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
    debug: jest.fn(),
  };
}

describe('AwarenessService document switching', () => {
  let logger: ReturnType<typeof createLoggerMock>;
  let awareness: AwarenessService;

  beforeEach(() => {
    jest.clearAllMocks();
    logger = createLoggerMock();
    awareness = new AwarenessService(logger as unknown as Logger);
  });

  it('drops the empty previous document when a socket moves', () => {
    awareness.addUser('doc-old', 'socket-a', 'user-a', 'Alice', 'a@test.com');

    awareness.addUser('doc-new', 'socket-a', 'user-a', 'Alice', 'a@test.com');

    expect(awareness.getActiveDocumentIds()).toEqual(['doc-new']);
    expect(awareness.getUserDocument('socket-a')).toBe('doc-new');
    expect(awareness.getDocumentUserCount('doc-old')).toBe(0);
    expect(logger.debug).toHaveBeenCalledWith(
      { oldDocumentId: 'doc-old', newDocumentId: 'doc-new', socketId: 'socket-a' },
      'awareness_socket_moved_documents',
    );
  });

  it('keeps the previous document alive when other users remain in it', () => {
    awareness.addUser('doc-old', 'socket-a', 'user-a', 'Alice', 'a@test.com');
    awareness.addUser('doc-old', 'socket-b', 'user-b', 'Bob', 'b@test.com');

    awareness.addUser('doc-new', 'socket-a', 'user-a', 'Alice', 'a@test.com');

    expect(awareness.getDocumentUserCount('doc-old')).toBe(1);
    expect(awareness.getDocumentUsers('doc-old').map((u) => u.userId)).toEqual([
      'user-b',
    ]);
  });

  it('re-adding a socket to the same document replaces its awareness entry', () => {
    const first = awareness.addUser('doc-1', 'socket-a', 'user-a', 'Alice', 'a@test.com');

    const second = awareness.addUser(
      'doc-1',
      'socket-a',
      'user-a',
      'Alice Renamed',
      'a@test.com',
    );

    expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    expect(second.color).not.toBe(first.color);
    expect(awareness.getDocumentUsers('doc-1')[0].displayName).toBe('Alice Renamed');
  });

  it('cycles through the palette and wraps around after 20 users', () => {
    const colors = new Set<string>();
    for (let i = 0; i < 20; i++) {
      colors.add(
        awareness.addUser('doc-1', `socket-${i}`, `user-${i}`, 'U', 'u@test.com').color,
      );
    }
    expect(colors.size).toBe(20);

    const wrapped = awareness.addUser('doc-1', 'socket-20', 'user-20', 'U', 'u@test.com');

    expect(wrapped.color).toBe(awareness.getDocumentUsers('doc-1')[0].color);
  });

  it('ignores a stale-user sweep for a socket already removed from its state', () => {
    awareness.addUser('doc-1', 'socket-a', 'user-a', 'Alice', 'a@test.com');
    awareness.removeUser('socket-a');

    expect(awareness.removeUser('socket-a')).toBeNull();
    expect(awareness.refreshActivity('socket-a')).toBe(false);
    expect(awareness.updateCursor('socket-a', null, null)).toBeNull();
    expect(awareness.setTyping('socket-a', true)).toBeNull();
    expect(awareness.getUserDocument('socket-a')).toBeNull();
  });
});
