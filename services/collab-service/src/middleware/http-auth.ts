import type { NextFunction, Request, Response } from 'express';
import type { Logger } from 'pino';
import { extractBearerToken, verifyAccessToken, type AuthenticatedUser } from './auth';

export function getRequestUser(res: Response): AuthenticatedUser {
  const user = res.locals.user as AuthenticatedUser | undefined;
  if (!user) {
    throw new Error('getRequestUser called on an unauthenticated request');
  }
  return user;
}

export function createHttpAuthMiddleware(jwtSecret: string, logger: Logger) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const token = extractBearerToken(req.headers.authorization);
    if (!token) {
      logger.warn({ path: req.path }, 'http_request_rejected: no token provided');
      res.status(401).json({ error: 'Authentication required' });
      return;
    }

    try {
      res.locals.user = verifyAccessToken(token, jwtSecret);
      next();
    } catch (err) {
      logger.warn(
        { path: req.path, error: (err as Error).message },
        'http_request_rejected: invalid token',
      );
      res.status(401).json({ error: 'Invalid or expired token' });
    }
  };
}
