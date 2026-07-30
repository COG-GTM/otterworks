import jwt from 'jsonwebtoken';
import type { Logger } from 'pino';
import type { Socket } from 'socket.io';
import {
  createAuthMiddleware,
  extractUserFromSocket,
  type AuthenticatedSocket,
  type AuthenticatedUser,
} from '../middleware/auth';

const JWT_SECRET = 'unit-test-secret';

const logger = {
  info: jest.fn(),
  debug: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
} as unknown as Logger;

function createSocket(handshake: {
  auth?: Record<string, unknown>;
  headers?: Record<string, string>;
}): Socket {
  return {
    id: 'sock-1',
    handshake: {
      auth: handshake.auth,
      headers: handshake.headers ?? {},
    },
  } as unknown as Socket;
}

describe('createAuthMiddleware', () => {
  const middleware = createAuthMiddleware(JWT_SECRET, logger);

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('accepts a valid handshake token and attaches the user', () => {
    const token = jwt.sign(
      { sub: 'user-1', email: 'a@test.com', name: 'Alice', roles: ['editor'] },
      JWT_SECRET,
      { expiresIn: '1h' },
    );
    const socket = createSocket({ auth: { token } });
    const next = jest.fn();

    middleware(socket, next);

    expect(next).toHaveBeenCalledWith();
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-1',
      email: 'a@test.com',
      displayName: 'Alice',
      roles: ['editor'],
    });
  });

  it('accepts a bearer token from the authorization header', () => {
    const token = jwt.sign({ sub: 'user-2', display_name: 'Bob' }, JWT_SECRET);
    const socket = createSocket({
      auth: {},
      headers: { authorization: `Bearer ${token}` },
    });
    const next = jest.fn();

    middleware(socket, next);

    expect(next).toHaveBeenCalledWith();
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-2',
      email: '',
      displayName: 'Bob',
      roles: [],
    });
  });

  it('falls back to Anonymous when the token carries no name claims', () => {
    const token = jwt.sign({ sub: 'user-3' }, JWT_SECRET);
    const socket = createSocket({ auth: { token } });

    middleware(socket, jest.fn());

    expect((socket as AuthenticatedSocket).user).toMatchObject({
      userId: 'user-3',
      displayName: 'Anonymous',
    });
  });

  it('prefers the "name" claim over "display_name"', () => {
    const token = jwt.sign(
      { sub: 'user-4', name: 'Preferred', display_name: 'Ignored' },
      JWT_SECRET,
    );
    const socket = createSocket({ auth: { token } });

    middleware(socket, jest.fn());

    expect((socket as AuthenticatedSocket).user?.displayName).toBe('Preferred');
  });

  it('rejects a handshake with no token at all', () => {
    const next = jest.fn();

    middleware(createSocket({ auth: {} }), next);

    expect(next).toHaveBeenCalledWith(expect.any(Error));
    expect(next.mock.calls[0][0].message).toBe('Authentication required');
    expect(logger.warn).toHaveBeenCalled();
  });

  it('rejects a handshake with neither auth nor headers', () => {
    const next = jest.fn();

    middleware(createSocket({}), next);

    expect(next.mock.calls[0][0].message).toBe('Authentication required');
  });

  it('rejects a token signed with the wrong secret', () => {
    const token = jwt.sign({ sub: 'user-5' }, 'some-other-secret');
    const next = jest.fn();

    middleware(createSocket({ auth: { token } }), next);

    expect(next.mock.calls[0][0].message).toBe('Invalid or expired token');
  });

  it('rejects an expired token', () => {
    const token = jwt.sign({ sub: 'user-6' }, JWT_SECRET, { expiresIn: '-1s' });
    const next = jest.fn();

    middleware(createSocket({ auth: { token } }), next);

    expect(next.mock.calls[0][0].message).toBe('Invalid or expired token');
    expect(logger.warn).toHaveBeenCalledWith(
      expect.objectContaining({ socketId: 'sock-1' }),
      'connection_rejected: invalid token',
    );
  });

  it('rejects a malformed token', () => {
    const next = jest.fn();

    middleware(createSocket({ auth: { token: 'not-a-jwt' } }), next);

    expect(next.mock.calls[0][0].message).toBe('Invalid or expired token');
  });
});

describe('extractUserFromSocket', () => {
  it('returns the authenticated user when the middleware attached one', () => {
    const user: AuthenticatedUser = {
      userId: 'user-1',
      email: 'a@test.com',
      displayName: 'Alice',
      roles: ['editor'],
    };
    const socket = { id: 'sock-1', user } as unknown as Socket;

    expect(extractUserFromSocket(socket)).toBe(user);
  });

  it('synthesises an anonymous identity for an unauthenticated socket', () => {
    const socket = { id: 'sock-9' } as unknown as Socket;

    expect(extractUserFromSocket(socket)).toEqual({
      userId: 'anon-sock-9',
      email: '',
      displayName: 'Anonymous',
      roles: [],
    });
  });
});
