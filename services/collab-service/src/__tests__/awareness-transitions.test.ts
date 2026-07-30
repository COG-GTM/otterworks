import type { Logger } from 'pino';
import { AwarenessService } from '../services/awareness';

const logger = {
  info: jest.fn(),
  debug: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
} as unknown as Logger;

describe('AwarenessService document transitions', () => {
  let awareness: AwarenessService;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    awareness = new AwarenessService(logger);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('moves a socket to the new document and drops the emptied old one', () => {
    awareness.addUser('doc-old', 'sock-1', 'user-1', 'Alice', 'a@test.com');

    awareness.addUser('doc-new', 'sock-1', 'user-1', 'Alice', 'a@test.com');

    expect(awareness.getUserDocument('sock-1')).toBe('doc-new');
    expect(awareness.getDocumentUserCount('doc-old')).toBe(0);
    expect(awareness.getDocumentUserCount('doc-new')).toBe(1);
    expect(awareness.getActiveDocumentIds()).toEqual(['doc-new']);
    expect(logger.debug).toHaveBeenCalledWith(
      { oldDocumentId: 'doc-old', newDocumentId: 'doc-new', socketId: 'sock-1' },
      'awareness_socket_moved_documents',
    );
  });

  it('keeps the old document alive when other users remain in it', () => {
    awareness.addUser('doc-old', 'sock-1', 'user-1', 'Alice', 'a@test.com');
    awareness.addUser('doc-old', 'sock-2', 'user-2', 'Bob', 'b@test.com');

    awareness.addUser('doc-new', 'sock-1', 'user-1', 'Alice', 'a@test.com');

    expect(awareness.getDocumentUserCount('doc-old')).toBe(1);
    expect(awareness.getActiveDocumentIds()).toEqual(['doc-old', 'doc-new']);
  });

  it('re-joining the same document replaces the entry without a move', () => {
    const first = awareness.addUser('doc-1', 'sock-1', 'user-1', 'Alice', 'a@test.com');

    const second = awareness.addUser('doc-1', 'sock-1', 'user-1', 'Alice', 'a@test.com');

    expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    expect(second.color).not.toBe(first.color);
    expect(logger.debug).not.toHaveBeenCalledWith(
      expect.anything(),
      'awareness_socket_moved_documents',
    );
  });

  it('cycles back through the colour palette once it is exhausted', () => {
    const colors: string[] = [];
    for (let i = 0; i < 21; i++) {
      colors.push(
        awareness.addUser('doc-1', `sock-${i}`, `user-${i}`, `U${i}`, `u${i}@test.com`)
          .color,
      );
    }

    expect(new Set(colors.slice(0, 20)).size).toBe(20);
    expect(colors[20]).toBe(colors[0]);
  });

  it('ignores cursor, typing and activity updates for unknown sockets', () => {
    expect(awareness.updateCursor('ghost', { index: 1, length: 0 }, null)).toBeNull();
    expect(awareness.setTyping('ghost', true)).toBeNull();
    expect(awareness.refreshActivity('ghost')).toBe(false);
    expect(awareness.getUserDocument('ghost')).toBeNull();
    expect(awareness.getDocumentUsers('ghost-doc')).toEqual([]);
  });

  it('records cursor, selection and typing state for a known socket', () => {
    awareness.addUser('doc-1', 'sock-1', 'user-1', 'Alice', 'a@test.com');

    const cursored = awareness.updateCursor(
      'sock-1',
      { index: 4, length: 0 },
      { index: 4, length: 6 },
    );
    const typing = awareness.setTyping('sock-1', true);

    expect(cursored).toMatchObject({ cursor: { index: 4, length: 0 } });
    expect(cursored?.selection).toEqual({ index: 4, length: 6 });
    expect(typing?.isTyping).toBe(true);
  });

  it('refreshActivity keeps an otherwise idle user out of the stale sweep', () => {
    awareness.addUser('doc-1', 'sock-active', 'user-1', 'Alice', 'a@test.com');
    awareness.addUser('doc-1', 'sock-idle', 'user-2', 'Bob', 'b@test.com');

    jest.advanceTimersByTime(400000);
    expect(awareness.refreshActivity('sock-active')).toBe(true);
    const removed = awareness.cleanupStaleUsers(300000);

    expect(removed).toEqual([
      { socketId: 'sock-idle', documentId: 'doc-1', userId: 'user-2' },
    ]);
    expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    expect(logger.info).toHaveBeenCalledWith(
      { count: 1 },
      'awareness_stale_users_cleaned',
    );
  });

  it('drops a document once all of its users go stale', () => {
    awareness.addUser('doc-1', 'sock-1', 'user-1', 'Alice', 'a@test.com');
    awareness.addUser('doc-2', 'sock-2', 'user-2', 'Bob', 'b@test.com');

    jest.advanceTimersByTime(400000);
    const removed = awareness.cleanupStaleUsers(300000);

    expect(removed).toHaveLength(2);
    expect(awareness.getActiveDocumentIds()).toEqual([]);
    expect(awareness.getUserDocument('sock-1')).toBeNull();
  });

  it('reports nothing when no user is stale', () => {
    awareness.addUser('doc-1', 'sock-1', 'user-1', 'Alice', 'a@test.com');

    expect(awareness.cleanupStaleUsers(300000)).toEqual([]);
    expect(logger.info).not.toHaveBeenCalled();
  });

  it('removeUser returns null for a socket it never saw', () => {
    expect(awareness.removeUser('ghost')).toBeNull();
  });
});
