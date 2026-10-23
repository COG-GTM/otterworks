import { AwarenessService } from '../services/awareness';
import { createMockLogger } from './qa-test-helpers';

describe('QA: AwarenessService edge cases', () => {
  let awareness: AwarenessService;

  beforeEach(() => {
    awareness = new AwarenessService(createMockLogger());
  });

  it('moves a socket between documents and drops the empty old document state', () => {
    awareness.addUser('doc-a', 's1', 'u1', 'A', '');
    awareness.addUser('doc-b', 's1', 'u1', 'A', '');
    expect(awareness.getUserDocument('s1')).toBe('doc-b');
    expect(awareness.getDocumentUserCount('doc-a')).toBe(0);
    expect(awareness.getActiveDocumentIds()).toEqual(['doc-b']);
  });

  it('keeps one entry when the same socket re-joins the same document', () => {
    awareness.addUser('doc-a', 's1', 'u1', 'A', '');
    awareness.addUser('doc-a', 's1', 'u1', 'A', '');
    expect(awareness.getDocumentUserCount('doc-a')).toBe(1);
  });

  it('cycles colors after the palette is exhausted', () => {
    const colors = Array.from(
      { length: 21 },
      (_, i) => awareness.addUser('doc', `s${i}`, `u${i}`, 'X', '').color,
    );
    expect(new Set(colors.slice(0, 20)).size).toBe(20);
    expect(colors[20]).toBe(colors[0]);
  });

  it('refreshActivity updates lastActive and returns false for unknown sockets', () => {
    const user = awareness.addUser('doc', 's1', 'u1', 'A', '');
    user.lastActive = 0;
    expect(awareness.refreshActivity('s1')).toBe(true);
    expect(awareness.getDocumentUsers('doc')[0].lastActive).toBeGreaterThan(0);
    expect(awareness.refreshActivity('missing')).toBe(false);
  });

  it('setTyping toggles typing and bumps lastActive', () => {
    const user = awareness.addUser('doc', 's1', 'u1', 'A', '');
    user.lastActive = 0;
    expect(awareness.setTyping('s1', true)?.isTyping).toBe(true);
    expect(awareness.setTyping('s1', false)?.isTyping).toBe(false);
    expect(user.lastActive).toBeGreaterThan(0);
  });

  it('updateCursor accepts null cursor/selection (user blurred editor)', () => {
    awareness.addUser('doc', 's1', 'u1', 'A', '');
    awareness.updateCursor('s1', { index: 3, length: 1 }, { index: 3, length: 4 });
    const cleared = awareness.updateCursor('s1', null, null);
    expect(cleared?.cursor).toBeNull();
    expect(cleared?.selection).toBeNull();
  });

  it('cleanupStaleUsers only removes the idle socket in a mixed document', () => {
    const idle = awareness.addUser('doc', 'idle', 'u1', 'A', '');
    awareness.addUser('doc', 'live', 'u2', 'B', '');
    idle.lastActive = Date.now() - 10_000;
    const removed = awareness.cleanupStaleUsers(5_000);
    expect(removed).toEqual([{ socketId: 'idle', documentId: 'doc', userId: 'u1' }]);
    expect(awareness.getDocumentUserCount('doc')).toBe(1);
    expect(awareness.getActiveDocumentIds()).toEqual(['doc']);
  });

  it('cleanupStaleUsers returns an empty list when nothing is idle', () => {
    awareness.addUser('doc', 's1', 'u1', 'A', '');
    expect(awareness.cleanupStaleUsers(60_000)).toEqual([]);
  });
});
