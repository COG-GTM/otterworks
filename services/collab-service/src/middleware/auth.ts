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
  iat?: number;
  exp?: number;
}

export interface TokenBinding {
  issuer: string;
  audience: string;
}

// Defaults match auth-service's jwt.issuer / jwt.audience; tenant deploys set
// JWT_AUDIENCE so a token from one tenant is rejected by every other tenant.
export const DEFAULT_TOKEN_BINDING: TokenBinding = {
  issuer: 'otterworks-auth-service',
  audience: 'otterworks',
};

export function verifyToken(
  token: string,
  jwtSecret: string,
  binding: TokenBinding = DEFAULT_TOKEN_BINDING,
): JwtPayload {
  const decoded = jwt.verify(token, jwtSecret, {
    algorithms: ['HS256', 'HS384', 'HS512'],
    issuer: binding.issuer,
    audience: binding.audience,
  });
  if (typeof decoded === 'string') {
    throw new Error('unexpected token payload');
  }
  return decoded as JwtPayload;
}

export function createAuthMiddleware(
  jwtSecret: string,
  logger: Logger,
  binding: TokenBinding = DEFAULT_TOKEN_BINDING,
) {
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
      const decoded = verifyToken(token, jwtSecret, binding);

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
