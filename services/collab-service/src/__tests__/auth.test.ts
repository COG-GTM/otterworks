import jwt from 'jsonwebtoken';
import type { Logger } from 'pino';
import type { Socket } from 'socket.io';
import type { ExtendedError } from 'socket.io/dist/namespace';
import {
  createAuthMiddleware,
  extractUserFromSocket,
  type AuthenticatedSocket,
} from '../middleware/auth';

const JWT_SECRET = 'auth-middleware-unit-test-secret';

const logger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as unknown as Logger;

interface Handshake {
  auth?: { token?: string };
  headers?: { authorization?: string };
}

function makeSocket(handshake: Handshake, id = 'socket-1'): Socket {
  return { id, handshake } as unknown as Socket;
}

function sign(payload: Record<string, unknown>, options?: jwt.SignOptions): string {
  // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
  return jwt.sign(payload, JWT_SECRET, options);
}

describe('createAuthMiddleware', () => {
  const middleware = createAuthMiddleware(JWT_SECRET, logger);

  beforeEach(() => {
    jest.clearAllMocks();
  });

  function run(socket: Socket): ExtendedError | undefined {
    let error: ExtendedError | undefined;
    middleware(socket, (err?: ExtendedError) => {
      error = err;
    });
    return error;
  }

  it('rejects a handshake with no auth and no authorization header', () => {
    const error = run(makeSocket({}));

    expect(error?.message).toBe('Authentication required');
    expect(logger.warn).toHaveBeenCalled();
  });

  it('rejects a handshake whose auth object carries no token', () => {
    const error = run(makeSocket({ auth: {}, headers: {} }));

    expect(error?.message).toBe('Authentication required');
  });

  it('authenticates a token supplied through handshake.auth', () => {
    const socket = makeSocket({
      auth: {
        token: sign({
          sub: 'user-1',
          email: 'a@test.com',
          name: 'Alice',
          roles: ['admin'],
        }),
      },
    });

    const error = run(socket);

    expect(error).toBeUndefined();
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-1',
      email: 'a@test.com',
      displayName: 'Alice',
      roles: ['admin'],
    });
  });

  it('authenticates a bearer token supplied through the authorization header', () => {
    const socket = makeSocket({
      auth: {},
      headers: { authorization: `Bearer ${sign({ sub: 'user-2', name: 'Bob' })}` },
    });

    const error = run(socket);

    expect(error).toBeUndefined();
    expect((socket as AuthenticatedSocket).user?.userId).toBe('user-2');
  });

  it('falls back to display_name and safe defaults for optional claims', () => {
    const socket = makeSocket({
      auth: { token: sign({ sub: 'user-3', display_name: 'Carol' }) },
    });

    run(socket);

    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-3',
      email: '',
      displayName: 'Carol',
      roles: [],
    });
  });

  it('defaults the display name to Anonymous when no name claim is present', () => {
    const socket = makeSocket({ auth: { token: sign({ sub: 'user-4' }) } });

    run(socket);

    expect((socket as AuthenticatedSocket).user?.displayName).toBe('Anonymous');
  });

  it('rejects a token signed with a different secret', () => {
    const socket = makeSocket({
      // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
      auth: { token: jwt.sign({ sub: 'user-5' }, 'some-other-secret') },
    });

    const error = run(socket);

    expect(error?.message).toBe('Invalid or expired token');
    expect((socket as AuthenticatedSocket).user).toBeUndefined();
  });

  it('rejects an expired token', () => {
    const socket = makeSocket({
      auth: { token: sign({ sub: 'user-6' }, { expiresIn: '-10s' }) },
    });

    const error = run(socket);

    expect(error?.message).toBe('Invalid or expired token');
  });

  it('rejects a malformed token', () => {
    const error = run(makeSocket({ auth: { token: 'not-a-jwt' } }));

    expect(error?.message).toBe('Invalid or expired token');
  });
});

describe('extractUserFromSocket', () => {
  it('returns the authenticated user attached by the middleware', () => {
    const socket = makeSocket({}, 'socket-auth');
    (socket as AuthenticatedSocket).user = {
      userId: 'user-7',
      email: 'd@test.com',
      displayName: 'Dave',
      roles: ['user'],
    };

    expect(extractUserFromSocket(socket)).toEqual({
      userId: 'user-7',
      email: 'd@test.com',
      displayName: 'Dave',
      roles: ['user'],
    });
  });

  it('falls back to an anonymous identity derived from the socket id', () => {
    expect(extractUserFromSocket(makeSocket({}, 'socket-anon'))).toEqual({
      userId: 'anon-socket-anon',
      email: '',
      displayName: 'Anonymous',
      roles: [],
    });
  });
});
