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
  accessToken?: string;
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

const ADMIN_ROLES = new Set(['ADMIN', 'ROLE_ADMIN']);

export function userFromToken(token: string, jwtSecret: string): AuthenticatedUser {
  const decoded = jwt.verify(token, jwtSecret) as JwtPayload;
  if (!decoded || typeof decoded.sub !== 'string' || !decoded.sub) {
    throw new Error('Token has no subject');
  }
  return {
    userId: decoded.sub,
    email: decoded.email || '',
    displayName: decoded.name || decoded.display_name || 'Anonymous',
    roles: Array.isArray(decoded.roles) ? decoded.roles : [],
  };
}

export function extractBearerToken(authorization: string | undefined): string | undefined {
  if (!authorization || !authorization.startsWith('Bearer ')) return undefined;
  const token = authorization.slice('Bearer '.length).trim();
  return token || undefined;
}

export function isAdmin(user: AuthenticatedUser): boolean {
  return user.roles.some((role) => ADMIN_ROLES.has(String(role).toUpperCase()));
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
      const user = userFromToken(token, jwtSecret);

      (socket as AuthenticatedSocket).user = user;
      (socket as AuthenticatedSocket).accessToken = token;

      logger.debug(
        { socketId: socket.id, userId: user.userId },
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

export function extractAccessToken(socket: Socket): string | undefined {
  return (socket as AuthenticatedSocket).accessToken;
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
