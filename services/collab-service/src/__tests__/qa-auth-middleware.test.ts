import type { Socket } from 'socket.io';
import {
  createAuthMiddleware,
  extractUserFromSocket,
  type AuthenticatedSocket,
} from '../middleware/auth';
import { QA_JWT_SECRET, createMockLogger, signToken } from './qa-test-helpers';

function fakeSocket(handshake: {
  auth?: Record<string, unknown>;
  headers?: Record<string, string>;
}) {
  return {
    id: 'sock-1',
    handshake: { auth: {}, headers: {}, ...handshake },
  } as unknown as Socket;
}

function runMiddleware(socket: Socket): Error | undefined {
  const middleware = createAuthMiddleware(QA_JWT_SECRET, createMockLogger());
  let result: Error | undefined;
  let called = false;
  middleware(socket, (err) => {
    called = true;
    result = err;
  });
  expect(called).toBe(true);
  return result;
}

describe('QA: createAuthMiddleware', () => {
  it('rejects a handshake without any token', () => {
    const err = runMiddleware(fakeSocket({}));
    expect(err?.message).toBe('Authentication required');
  });

  it('rejects a malformed token', () => {
    const err = runMiddleware(fakeSocket({ auth: { token: 'abc.def.ghi' } }));
    expect(err?.message).toBe('Invalid or expired token');
  });

  it('rejects a token signed with a different secret', () => {
    const token = signToken({ sub: 'u1' }, { expiresIn: '1h' }, 'some-other-secret');
    const err = runMiddleware(fakeSocket({ auth: { token } }));
    expect(err?.message).toBe('Invalid or expired token');
  });

  it('rejects an expired token', () => {
    const token = signToken({ sub: 'u1', exp: Math.floor(Date.now() / 1000) - 60 }, {});
    const err = runMiddleware(fakeSocket({ auth: { token } }));
    expect(err?.message).toBe('Invalid or expired token');
  });

  it('rejects an unsigned (alg=none) token', () => {
    const header = Buffer.from(JSON.stringify({ alg: 'none', typ: 'JWT' })).toString(
      'base64url',
    );
    const body = Buffer.from(JSON.stringify({ sub: 'attacker' })).toString('base64url');
    const err = runMiddleware(fakeSocket({ auth: { token: `${header}.${body}.` } }));
    expect(err?.message).toBe('Invalid or expired token');
  });

  it('accepts a valid token from handshake.auth and attaches the user', () => {
    const token = signToken({
      sub: 'user-42',
      email: 'u42@example.test',
      name: 'User Forty Two',
      roles: ['editor'],
    });
    const socket = fakeSocket({ auth: { token } });
    expect(runMiddleware(socket)).toBeUndefined();
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-42',
      email: 'u42@example.test',
      displayName: 'User Forty Two',
      roles: ['editor'],
    });
  });

  it('falls back to the Authorization: Bearer header', () => {
    const token = signToken({ sub: 'header-user' });
    const socket = fakeSocket({ headers: { authorization: `Bearer ${token}` } });
    expect(runMiddleware(socket)).toBeUndefined();
    expect((socket as AuthenticatedSocket).user?.userId).toBe('header-user');
  });

  it('prefers display_name when name is absent and defaults to Anonymous', () => {
    const withDisplayName = fakeSocket({
      auth: { token: signToken({ sub: 'a', display_name: 'Disp' }) },
    });
    runMiddleware(withDisplayName);
    expect((withDisplayName as AuthenticatedSocket).user?.displayName).toBe('Disp');

    const bare = fakeSocket({ auth: { token: signToken({ sub: 'b' }) } });
    runMiddleware(bare);
    expect((bare as AuthenticatedSocket).user).toEqual({
      userId: 'b',
      email: '',
      displayName: 'Anonymous',
      roles: [],
    });
  });

  // Finding COLLAB-04: auth-service issues refresh tokens (type=refresh) signed with the same
  // key; collab-service never checks the `type` claim, so a long-lived refresh token is accepted
  // as a websocket credential.
  it.failing(
    'rejects refresh tokens (type=refresh) as websocket credentials [COLLAB-04]',
    () => {
      const token = signToken(
        { sub: 'user-1', type: 'refresh', jti: 'r-1' },
        { expiresIn: '7d' },
      );
      const err = runMiddleware(fakeSocket({ auth: { token } }));
      expect(err).toBeDefined();
    },
  );

  // Finding COLLAB-04 (cont.): a token without `sub` is accepted and yields userId undefined.
  it.failing('rejects tokens without a subject claim [COLLAB-04]', () => {
    const err = runMiddleware(
      fakeSocket({ auth: { token: signToken({ email: 'x@y.z' }) } }),
    );
    expect(err).toBeDefined();
  });
});

describe('QA: extractUserFromSocket', () => {
  it('returns the authenticated user when present', () => {
    const socket = {
      id: 's',
      user: { userId: 'u', email: '', displayName: 'U', roles: [] },
    };
    expect(extractUserFromSocket(socket as unknown as Socket).userId).toBe('u');
  });

  it('returns an anonymous placeholder keyed by socket id otherwise', () => {
    expect(extractUserFromSocket({ id: 'abc' } as unknown as Socket)).toEqual({
      userId: 'anon-abc',
      email: '',
      displayName: 'Anonymous',
      roles: [],
    });
  });
});
