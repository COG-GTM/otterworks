import type { Logger } from 'pino';
import jwt from 'jsonwebtoken';
import type { Socket } from 'socket.io';
import {
  createAuthMiddleware,
  extractUserFromSocket,
  type AuthenticatedSocket,
} from '../middleware/auth';

const JWT_SECRET = 'test-secret-key-for-auth-unit-tests';

const loggerMock = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
};
const logger = loggerMock as unknown as Logger;

function socketWith(handshake: Record<string, unknown>): Socket {
  return { id: 'socket-1', handshake } as unknown as Socket;
}

describe('createAuthMiddleware', () => {
  const middleware = createAuthMiddleware(JWT_SECRET, logger);

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('rejects a handshake with neither auth token nor authorization header', () => {
    const next = jest.fn();

    middleware(socketWith({ auth: {}, headers: {} }), next);

    expect(next).toHaveBeenCalledWith(expect.any(Error));
    expect(next.mock.calls[0][0].message).toBe('Authentication required');
    expect(loggerMock.warn).toHaveBeenCalled();
  });

  it('rejects a handshake with no auth and no headers object at all', () => {
    const next = jest.fn();

    middleware(socketWith({}), next);

    expect(next.mock.calls[0][0].message).toBe('Authentication required');
  });

  it('accepts a token from handshake.auth and attaches the user', () => {
    const next = jest.fn();
    const token = jwt.sign(
      {
        sub: 'user-1',
        email: 'user1@test.com',
        name: 'User One',
        roles: ['user', 'editor'],
      },
      JWT_SECRET,
    );
    const socket = socketWith({ auth: { token } });

    middleware(socket, next);

    expect(next).toHaveBeenCalledWith();
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-1',
      email: 'user1@test.com',
      displayName: 'User One',
      roles: ['user', 'editor'],
    });
  });

  it('accepts a Bearer token from the authorization header', () => {
    const next = jest.fn();
    const token = jwt.sign({ sub: 'user-2', email: 'u2@test.com' }, JWT_SECRET);
    const socket = socketWith({ headers: { authorization: `Bearer ${token}` } });

    middleware(socket, next);

    expect(next).toHaveBeenCalledWith();
    expect((socket as AuthenticatedSocket).user?.userId).toBe('user-2');
  });

  it('falls back to display_name then Anonymous, and defaults email and roles', () => {
    const withSnakeCase = socketWith({
      auth: {
        token: jwt.sign({ sub: 'user-3', display_name: 'Snake Case' }, JWT_SECRET),
      },
    });
    const withNothing = socketWith({
      auth: { token: jwt.sign({ sub: 'user-4' }, JWT_SECRET) },
    });

    middleware(withSnakeCase, jest.fn());
    middleware(withNothing, jest.fn());

    expect((withSnakeCase as AuthenticatedSocket).user).toEqual({
      userId: 'user-3',
      email: '',
      displayName: 'Snake Case',
      roles: [],
    });
    expect((withNothing as AuthenticatedSocket).user?.displayName).toBe('Anonymous');
  });

  it('rejects a token signed with the wrong secret', () => {
    const next = jest.fn();
    const token = jwt.sign({ sub: 'user-5' }, 'a-different-secret');

    middleware(socketWith({ auth: { token } }), next);

    expect(next.mock.calls[0][0].message).toBe('Invalid or expired token');
  });

  it('rejects an expired token', () => {
    const next = jest.fn();
    const token = jwt.sign({ sub: 'user-6' }, JWT_SECRET, { expiresIn: '-1s' });
    const socket = socketWith({ auth: { token } });

    middleware(socket, next);

    expect(next.mock.calls[0][0].message).toBe('Invalid or expired token');
    expect((socket as AuthenticatedSocket).user).toBeUndefined();
  });

  it('rejects a structurally invalid token', () => {
    const next = jest.fn();

    middleware(socketWith({ auth: { token: 'not-a-jwt' } }), next);

    expect(next.mock.calls[0][0].message).toBe('Invalid or expired token');
  });
});

describe('extractUserFromSocket', () => {
  it('returns the authenticated user when the middleware attached one', () => {
    const socket = socketWith({ auth: {} }) as AuthenticatedSocket;
    socket.user = {
      userId: 'user-7',
      email: 'u7@test.com',
      displayName: 'User Seven',
      roles: ['admin'],
    };

    expect(extractUserFromSocket(socket)).toBe(socket.user);
  });

  it('synthesises an anonymous identity from the socket id otherwise', () => {
    expect(extractUserFromSocket(socketWith({ auth: {} }))).toEqual({
      userId: 'anon-socket-1',
      email: '',
      displayName: 'Anonymous',
      roles: [],
    });
  });
});
