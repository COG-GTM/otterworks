import jwt from 'jsonwebtoken';
import type { Logger } from 'pino';
import type { Socket } from 'socket.io';
import {
  createAuthMiddleware,
  extractUserFromSocket,
  type AuthenticatedSocket,
} from '../middleware/auth';

const JWT_SECRET = 'unit-test-secret'; // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret

function createLoggerMock() {
  return {
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
    debug: jest.fn(),
  };
}

function createSocket(handshake: Record<string, unknown>): Socket {
  return { id: 'socket-1', handshake } as unknown as Socket;
}

function sign(payload: Record<string, unknown>, options?: jwt.SignOptions): string {
  return jwt.sign(payload, JWT_SECRET, options); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

describe('createAuthMiddleware', () => {
  let logger: ReturnType<typeof createLoggerMock>;
  let middleware: ReturnType<typeof createAuthMiddleware>;
  let next: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    logger = createLoggerMock();
    middleware = createAuthMiddleware(JWT_SECRET, logger as unknown as Logger);
    next = jest.fn();
  });

  it('rejects a handshake with no auth and no headers', () => {
    middleware(createSocket({}), next);

    expect(next).toHaveBeenCalledWith(new Error('Authentication required'));
    expect(logger.warn).toHaveBeenCalledWith(
      { socketId: 'socket-1' },
      'connection_rejected: no token provided',
    );
  });

  it('rejects a handshake whose authorization header is absent', () => {
    middleware(createSocket({ auth: {}, headers: {} }), next);

    expect(next).toHaveBeenCalledWith(new Error('Authentication required'));
  });

  it('authenticates a token supplied via handshake auth', () => {
    const socket = createSocket({
      auth: {
        token: sign({
          sub: 'user-1',
          email: 'user-1@test.com',
          name: 'Alice',
          roles: ['user', 'editor'],
        }),
      },
    });

    middleware(socket, next);

    expect(next).toHaveBeenCalledWith();
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-1',
      email: 'user-1@test.com',
      displayName: 'Alice',
      roles: ['user', 'editor'],
    });
  });

  it('authenticates a Bearer token supplied via the authorization header', () => {
    const socket = createSocket({
      auth: {},
      headers: { authorization: `Bearer ${sign({ sub: 'user-2', name: 'Bob' })}` },
    });

    middleware(socket, next);

    expect(next).toHaveBeenCalledWith();
    expect((socket as AuthenticatedSocket).user?.userId).toBe('user-2');
  });

  it('falls back to display_name when no name claim is present', () => {
    const socket = createSocket({
      auth: { token: sign({ sub: 'user-3', display_name: 'Carol' }) },
    });

    middleware(socket, next);

    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-3',
      email: '',
      displayName: 'Carol',
      roles: [],
    });
  });

  it('defaults the display name to Anonymous when the token carries no name claims', () => {
    const socket = createSocket({ auth: { token: sign({ sub: 'user-4' }) } });

    middleware(socket, next);

    expect((socket as AuthenticatedSocket).user?.displayName).toBe('Anonymous');
  });

  it('rejects a token signed with a different secret', () => {
    const socket = createSocket({
      auth: { token: jwt.sign({ sub: 'user-5' }, 'other-secret') }, // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
    });

    middleware(socket, next);

    expect(next).toHaveBeenCalledWith(new Error('Invalid or expired token'));
    expect((socket as AuthenticatedSocket).user).toBeUndefined();
    expect(logger.warn).toHaveBeenCalledWith(
      { socketId: 'socket-1', error: 'invalid signature' },
      'connection_rejected: invalid token',
    );
  });

  it('rejects an expired token', () => {
    const socket = createSocket({
      auth: { token: sign({ sub: 'user-6' }, { expiresIn: '-1s' }) },
    });

    middleware(socket, next);

    expect(next).toHaveBeenCalledWith(new Error('Invalid or expired token'));
  });

  it('rejects a malformed token', () => {
    middleware(createSocket({ auth: { token: 'not-a-jwt' } }), next);

    expect(next).toHaveBeenCalledWith(new Error('Invalid or expired token'));
  });
});

describe('extractUserFromSocket', () => {
  it('returns the authenticated user when the middleware has run', () => {
    const socket = createSocket({ auth: {} }) as AuthenticatedSocket;
    socket.user = {
      userId: 'user-1',
      email: 'user-1@test.com',
      displayName: 'Alice',
      roles: ['user'],
    };

    expect(extractUserFromSocket(socket)).toBe(socket.user);
  });

  it('synthesises an anonymous user when the socket is unauthenticated', () => {
    expect(extractUserFromSocket(createSocket({ auth: {} }))).toEqual({
      userId: 'anon-socket-1',
      email: '',
      displayName: 'Anonymous',
      roles: [],
    });
  });
});
