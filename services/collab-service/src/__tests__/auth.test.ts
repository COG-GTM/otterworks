import jwt from 'jsonwebtoken';
import type { Socket } from 'socket.io';
import {
  createAuthMiddleware,
  extractUserFromSocket,
  type AuthenticatedSocket,
} from '../middleware/auth';

const SECRET = 'auth-test-secret';

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

function sign(payload: Record<string, unknown>, secret = SECRET): string {
  return jwt.sign(payload, secret, { expiresIn: '1h' }); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

function fakeSocket(handshake: Record<string, unknown>): Socket {
  return { id: 'sock-1', handshake } as unknown as Socket;
}

describe('createAuthMiddleware', () => {
  const middleware = createAuthMiddleware(SECRET, mockLogger);

  beforeEach(() => jest.clearAllMocks());

  it('rejects when no token is present in auth or headers', () => {
    const next = jest.fn();
    middleware(fakeSocket({ auth: {}, headers: {} }), next);
    expect(next).toHaveBeenCalledWith(new Error('Authentication required'));
  });

  it('rejects when handshake has neither auth nor headers', () => {
    const next = jest.fn();
    middleware(fakeSocket({}), next);
    expect(next).toHaveBeenCalledWith(new Error('Authentication required'));
  });

  it('rejects an invalid token', () => {
    const next = jest.fn();
    middleware(fakeSocket({ auth: { token: sign({ sub: 'u1' }, 'other') } }), next);
    expect(next).toHaveBeenCalledWith(new Error('Invalid or expired token'));
    expect((mockLogger as { warn: jest.Mock }).warn).toHaveBeenCalled();
  });

  it('accepts a bearer token from the Authorization header', () => {
    const next = jest.fn();
    const socket = fakeSocket({
      headers: { authorization: `Bearer ${sign({ sub: 'u2', display_name: 'Dee' })}` },
    });
    middleware(socket, next);
    expect(next).toHaveBeenCalledWith();
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'u2',
      email: '',
      displayName: 'Dee',
      roles: [],
    });
  });

  it('prefers name and copies email/roles from the token', () => {
    const next = jest.fn();
    const socket = fakeSocket({
      auth: {
        token: sign({
          sub: 'u3',
          name: 'Ann',
          display_name: 'ignored',
          email: 'ann@x.io',
          roles: ['admin'],
        }),
      },
    });
    middleware(socket, next);
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'u3',
      email: 'ann@x.io',
      displayName: 'Ann',
      roles: ['admin'],
    });
  });

  it('falls back to Anonymous when the token has no name claims', () => {
    const next = jest.fn();
    const socket = fakeSocket({ auth: { token: sign({ sub: 'u4' }) } });
    middleware(socket, next);
    expect((socket as AuthenticatedSocket).user?.displayName).toBe('Anonymous');
  });
});

describe('extractUserFromSocket', () => {
  it('returns the authenticated user when present', () => {
    const user = { userId: 'u1', email: 'e', displayName: 'U', roles: [] };
    const socket = { id: 's', user } as unknown as Socket;
    expect(extractUserFromSocket(socket)).toBe(user);
  });

  it('returns an anonymous user derived from the socket id otherwise', () => {
    const socket = { id: 'abc' } as unknown as Socket;
    expect(extractUserFromSocket(socket)).toEqual({
      userId: 'anon-abc',
      email: '',
      displayName: 'Anonymous',
      roles: [],
    });
  });
});
