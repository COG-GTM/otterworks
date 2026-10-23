import jwt from 'jsonwebtoken';
import type { Socket } from 'socket.io';
import {
  AuthenticatedSocket,
  createAuthMiddleware,
  verifyAccessToken,
} from '../middleware/auth';

const JWT_SECRET = 'test-secret-key-for-unit-tests';

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
  child: jest.fn().mockReturnThis(),
} as never;

function sign(
  payload: Record<string, unknown>,
  expiresIn: string | number = '1h',
): string {
  return jwt.sign(payload, JWT_SECRET, { expiresIn } as jwt.SignOptions); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

function fakeSocket(token: string): Socket {
  return {
    id: 'socket-1',
    handshake: { auth: { token }, headers: {} },
  } as unknown as Socket;
}

describe('verifyAccessToken', () => {
  it('accepts an access token', () => {
    const payload = verifyAccessToken(
      sign({ sub: 'user-1', type: 'access' }),
      JWT_SECRET,
    );
    expect(payload.sub).toBe('user-1');
  });

  it.each([
    ['refresh token', { sub: 'user-1', type: 'refresh', jti: 'jti-1' }],
    ['token without a type claim', { sub: 'user-1' }],
    ['token with an unknown type', { sub: 'user-1', type: 'password-reset' }],
  ])('rejects a %s', (_name, payload) => {
    expect(() => verifyAccessToken(sign(payload, '30d'), JWT_SECRET)).toThrow(
      'Token is not an access token',
    );
  });

  it('rejects a token signed with another secret', () => {
    const token = jwt.sign({ sub: 'user-1', type: 'access' }, 'other-secret'); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
    expect(() => verifyAccessToken(token, JWT_SECRET)).toThrow();
  });
});

describe('createAuthMiddleware', () => {
  const middleware = createAuthMiddleware(JWT_SECRET, mockLogger);

  it('authenticates a socket presenting an access token', () => {
    const socket = fakeSocket(sign({ sub: 'user-1', type: 'access', name: 'Otter' }));
    const next = jest.fn();
    middleware(socket, next);
    expect(next).toHaveBeenCalledWith();
    expect((socket as AuthenticatedSocket).user?.userId).toBe('user-1');
  });

  it('rejects a socket presenting a refresh token', () => {
    const socket = fakeSocket(
      sign({ sub: 'user-1', type: 'refresh', jti: 'jti-1' }, '30d'),
    );
    const next = jest.fn();
    middleware(socket, next);
    expect(next).toHaveBeenCalledWith(expect.any(Error));
    expect((socket as AuthenticatedSocket).user).toBeUndefined();
  });
});
