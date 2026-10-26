import jwt from 'jsonwebtoken';
import type { Socket } from 'socket.io';
import type { Logger } from 'pino';
import { createAuthMiddleware, type AuthenticatedSocket } from '../middleware/auth';

const SECRET = 'collab-test-secret-0123456789abcdef';

const logger = {
  warn: jest.fn(),
  debug: jest.fn(),
} as unknown as Logger;

function fakeSocket(token?: string): Socket {
  return {
    id: 'sock-1',
    handshake: { auth: token ? { token } : {}, headers: {} },
  } as unknown as Socket;
}

function authenticate(token?: string): { err?: Error; socket: Socket } {
  const socket = fakeSocket(token);
  let err: Error | undefined;
  createAuthMiddleware(SECRET, logger)(socket, (e) => {
    err = e;
  });
  return { err, socket };
}

describe('createAuthMiddleware', () => {
  it('accepts a token signed with the configured secret', () => {
    for (const algorithm of ['HS256', 'HS384', 'HS512'] as const) {
      const token = jwt.sign({ sub: 'user-1', email: 'u@test.com' }, SECRET, {
        algorithm,
      });
      const { err, socket } = authenticate(token);
      expect(err).toBeUndefined();
      expect((socket as AuthenticatedSocket).user?.userId).toBe('user-1');
    }
  });

  it('rejects a token forged with the old public default secret', () => {
    const forged = jwt.sign({ sub: 'victim', roles: ['admin'] }, 'otterworks-dev-secret');
    const { err, socket } = authenticate(forged);
    expect(err?.message).toBe('Invalid or expired token');
    expect((socket as AuthenticatedSocket).user).toBeUndefined();
  });

  it('rejects an unsigned (alg: none) token', () => {
    const unsigned = jwt.sign({ sub: 'victim' }, '', { algorithm: 'none' });
    const { err } = authenticate(unsigned);
    expect(err?.message).toBe('Invalid or expired token');
  });

  it('rejects a connection without a token', () => {
    const { err } = authenticate();
    expect(err?.message).toBe('Authentication required');
  });
});
