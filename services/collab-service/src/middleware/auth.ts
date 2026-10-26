import jwt from 'jsonwebtoken';
import type { Socket } from 'socket.io';
import type { ExtendedError } from 'socket.io/dist/namespace';
import type { Logger } from 'pino';

export interface AuthenticatedUser {
  userId: string;
  email: string;
  displayName: string;
  roles: string[];
}

export interface AuthenticatedSocket extends Socket {
  user?: AuthenticatedUser;
}

interface JwtPayload {
  sub: string;
  email?: string;
  name?: string;
  display_name?: string;
  roles?: string[];
  type?: string;
  iat?: number;
  exp?: number;
}

/**
 * Verify a bearer token and require it to be an access token. auth-service signs
 * refresh tokens with the same key, so signature checks alone would let a 30-day
 * refresh token act as a login. Tokens without a `type` claim count as access.
 */
export function verifyAccessToken(token: string, jwtSecret: string): JwtPayload {
  const decoded = jwt.verify(token, jwtSecret);
  if (typeof decoded === 'string') {
    throw new Error('Unexpected token payload');
  }
  const payload = decoded as JwtPayload;
  if ((payload.type ?? 'access') !== 'access') {
    throw new Error(`${payload.type} tokens cannot be used as access tokens`);
  }
  return payload;
}

export function createAuthMiddleware(jwtSecret: string, logger: Logger) {
  return (socket: Socket, next: (err?: ExtendedError) => void): void => {
    const token =
      socket.handshake.auth?.token ||
      socket.handshake.headers?.authorization?.replace('Bearer ', '');

    if (!token) {
      logger.warn({ socketId: socket.id }, 'connection_rejected: no token provided');
      next(new Error('Authentication required'));
      return;
    }

    try {
      const decoded = verifyAccessToken(token, jwtSecret);

      (socket as AuthenticatedSocket).user = {
        userId: decoded.sub,
        email: decoded.email || '',
        displayName: decoded.name || decoded.display_name || 'Anonymous',
        roles: decoded.roles || [],
      };

      logger.debug(
        { socketId: socket.id, userId: decoded.sub },
        'connection_authenticated',
      );
      next();
    } catch (err) {
      logger.warn(
        { socketId: socket.id, error: (err as Error).message },
        'connection_rejected: invalid token',
      );
      next(new Error('Invalid or expired token'));
    }
  };
}

export function extractUserFromSocket(socket: Socket): AuthenticatedUser {
  const authSocket = socket as AuthenticatedSocket;
  return (
    authSocket.user || {
      userId: `anon-${socket.id}`,
      email: '',
      displayName: 'Anonymous',
      roles: [],
    }
  );
}
