import type { IncomingMessage } from 'http';
import jwt from 'jsonwebtoken';
import {
  WsTicketStore,
  authenticateUpgrade,
  verifyBearerToken,
} from '../middleware/ws-auth';

const JWT_SECRET = 'test-secret-key-for-unit-tests';

function createToken(payload: Record<string, unknown>): string {
  return jwt.sign(payload, JWT_SECRET, { expiresIn: '1h' }); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

function upgradeRequest(url: string, authorization?: string): IncomingMessage {
  return { url, headers: authorization ? { authorization } : {} } as IncomingMessage;
}

describe('WsTicketStore', () => {
  it('issues a ticket that can be consumed exactly once', () => {
    const store = new WsTicketStore();
    const { ticket, expiresInSeconds } = store.issue('user-1');

    expect(ticket.length).toBeGreaterThanOrEqual(40);
    expect(expiresInSeconds).toBe(30);
    expect(store.consume(ticket)).toBe('user-1');
    expect(store.consume(ticket)).toBeNull();
  });

  it('rejects expired tickets', () => {
    let now = 1_000;
    const store = new WsTicketStore(5_000, () => now);
    const { ticket } = store.issue('user-1');

    now += 5_000;
    expect(store.consume(ticket)).toBeNull();
  });

  it('prunes expired tickets when issuing new ones', () => {
    let now = 1_000;
    const store = new WsTicketStore(5_000, () => now);
    store.issue('user-1');
    store.issue('user-2');

    now += 6_000;
    store.issue('user-3');
    expect(store.size).toBe(1);
  });

  it('rejects unknown tickets', () => {
    expect(new WsTicketStore().consume('nope')).toBeNull();
  });
});

describe('verifyBearerToken', () => {
  it('accepts a valid bearer JWT', () => {
    const token = createToken({ sub: 'user-1' });
    expect(verifyBearerToken(`Bearer ${token}`, JWT_SECRET)).toEqual({
      userId: 'user-1',
    });
  });

  it('rejects missing, malformed, or forged tokens', () => {
    const forged = jwt.sign({ sub: 'user-1' }, 'wrong-secret'); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
    expect(verifyBearerToken(undefined, JWT_SECRET)).toBeNull();
    expect(verifyBearerToken(createToken({ sub: 'user-1' }), JWT_SECRET)).toBeNull();
    expect(verifyBearerToken(`Bearer ${forged}`, JWT_SECRET)).toBeNull();
    expect(verifyBearerToken(`Bearer ${createToken({})}`, JWT_SECRET)).toBeNull();
  });
});

describe('authenticateUpgrade', () => {
  it('accepts a JWT in the Authorization header', () => {
    const token = createToken({ sub: 'user-1' });
    const req = upgradeRequest('/document-abc', `Bearer ${token}`);
    expect(authenticateUpgrade(req, JWT_SECRET, new WsTicketStore())).toEqual({
      userId: 'user-1',
    });
  });

  it('does not accept a JWT in the query string', () => {
    const token = createToken({ sub: 'user-1' });
    const req = upgradeRequest(`/document-abc?token=${token}`);
    expect(authenticateUpgrade(req, JWT_SECRET, new WsTicketStore())).toBeNull();
  });

  it('does not accept a JWT passed as a ticket', () => {
    const token = createToken({ sub: 'user-1' });
    const req = upgradeRequest(`/document-abc?ticket=${token}`);
    expect(authenticateUpgrade(req, JWT_SECRET, new WsTicketStore())).toBeNull();
  });

  it('accepts a ticket once and rejects its replay', () => {
    const store = new WsTicketStore();
    const { ticket } = store.issue('user-1');
    const req = upgradeRequest(`/document-abc?ticket=${encodeURIComponent(ticket)}`);

    expect(authenticateUpgrade(req, JWT_SECRET, store)).toEqual({ userId: 'user-1' });
    expect(authenticateUpgrade(req, JWT_SECRET, store)).toBeNull();
  });

  it('rejects upgrades without credentials', () => {
    expect(
      authenticateUpgrade(
        upgradeRequest('/document-abc'),
        JWT_SECRET,
        new WsTicketStore(),
      ),
    ).toBeNull();
  });
});
