import { AwarenessService } from '../services/awareness';

const logger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

describe('AwarenessService document transitions', () => {
  let awareness: AwarenessService;

  beforeEach(() => {
    jest.clearAllMocks();
    awareness = new AwarenessService(logger);
  });

  it('moves a socket to the new document and drops the emptied old one', () => {
    awareness.addUser('doc-old', 'sock-a', 'user-a', 'Alice', 'a@test.com');

    awareness.addUser('doc-new', 'sock-a', 'user-a', 'Alice', 'a@test.com');

    expect(awareness.getUserDocument('sock-a')).toBe('doc-new');
    expect(awareness.getDocumentUserCount('doc-old')).toBe(0);
    expect(awareness.getActiveDocumentIds()).toEqual(['doc-new']);
  });

  it('keeps the old document alive when other users remain in it', () => {
    awareness.addUser('doc-old', 'sock-a', 'user-a', 'Alice', 'a@test.com');
    awareness.addUser('doc-old', 'sock-b', 'user-b', 'Bob', 'b@test.com');

    awareness.addUser('doc-new', 'sock-a', 'user-a', 'Alice', 'a@test.com');

    expect(awareness.getDocumentUserCount('doc-old')).toBe(1);
    expect(awareness.getDocumentUsers('doc-old').map((u) => u.userId)).toEqual([
      'user-b',
    ]);
    expect(awareness.getActiveDocumentIds().sort()).toEqual(['doc-new', 'doc-old']);
  });

  it('re-joining the same document replaces the entry without dropping the document', () => {
    const first = awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');

    const second = awareness.addUser('doc-1', 'sock-a', 'user-a', 'Alice', 'a@test.com');

    expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    expect(second.color).not.toBe(first.color);
  });

  it('is a no-op when removing, refreshing or updating an unknown socket', () => {
    expect(awareness.removeUser('ghost')).toBeNull();
    expect(awareness.refreshActivity('ghost')).toBe(false);
    expect(awareness.updateCursor('ghost', null, null)).toBeNull();
    expect(awareness.setTyping('ghost', true)).toBeNull();
    expect(awareness.getUserDocument('ghost')).toBeNull();
  });
});
