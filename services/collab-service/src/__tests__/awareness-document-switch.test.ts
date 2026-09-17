import type { Logger } from 'pino';
import { AwarenessService } from '../services/awareness';

const logger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as unknown as Logger;

describe('AwarenessService document switching', () => {
  let awareness: AwarenessService;

  beforeEach(() => {
    jest.clearAllMocks();
    awareness = new AwarenessService(logger);
  });

  it('drops the socket from its previous document when it joins another one', () => {
    awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');

    awareness.addUser('doc-2', 'sock-a', 'user-a', 'Alice', 'a@test.com');

    expect(awareness.getUserDocument('sock-a')).toBe('doc-2');
    expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    expect(awareness.getDocumentUserCount('doc-2')).toBe(1);
    expect(awareness.getActiveDocumentIds()).toEqual(['doc-2']);
    expect(logger.debug).toHaveBeenCalledWith(
      { oldDocumentId: 'doc-1', newDocumentId: 'doc-2', socketId: 'sock-a' },
      'awareness_socket_moved_documents',
    );
  });

  it('keeps the previous document alive when other users remain in it', () => {
    awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
    awareness.addUser('doc-1', 'sock-b', 'user-b', 'Bob', 'b@test.com');

    awareness.addUser('doc-2', 'sock-a', 'user-a', 'Alice', 'a@test.com');

    expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    expect(awareness.getDocumentUsers('doc-1').map((u) => u.userId)).toEqual(['user-b']);
    expect(awareness.getActiveDocumentIds()).toEqual(['doc-1', 'doc-2']);
  });

  it('re-registering the same socket in the same document resets its awareness', () => {
    awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
    awareness.updateCursor('sock-a', { index: 7, length: 2 }, null);
    awareness.setTyping('sock-a', true);

    const readded = awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');

    expect(readded.cursor).toBeNull();
    expect(readded.isTyping).toBe(false);
    expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    expect(logger.debug).not.toHaveBeenCalledWith(
      expect.anything(),
      'awareness_socket_moved_documents',
    );
  });

  it('gives each newly registered user a distinct colour from the palette', () => {
    const first = awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');
    const second = awareness.addUser('doc-1', 'sock-b', 'user-b', 'Bob', 'b@test.com');

    expect(first.color).not.toBe(second.color);
    expect(first.color).toMatch(/^#[0-9A-F]{6}$/i);
  });
});
