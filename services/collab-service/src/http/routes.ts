import { Router, type Request, type Response, type NextFunction } from 'express';
import type { Logger } from 'pino';
import { verifyAccessToken, type AuthenticatedUser } from '../middleware/auth';
import type { PresenceHandler } from '../handlers/presence';
import type { DocumentAccessChecker } from '../services/document-access';

interface AuthenticatedLocals {
  user: AuthenticatedUser;
  token: string;
}

const ADMIN_ROLES = new Set(['ADMIN', 'OWNER']);

function isAdmin(user: AuthenticatedUser): boolean {
  return user.roles.some((role) => ADMIN_ROLES.has(String(role).toUpperCase()));
}

export function createHttpAuthMiddleware(jwtSecret: string, logger: Logger) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const header = req.headers.authorization;
    const token = header?.startsWith('Bearer ')
      ? header.slice('Bearer '.length).trim()
      : '';

    if (!token) {
      res.status(401).json({ error: 'Authentication required' });
      return;
    }

    try {
      const locals: AuthenticatedLocals = {
        user: verifyAccessToken(token, jwtSecret),
        token,
      };
      res.locals.auth = locals;
      next();
    } catch (err) {
      logger.warn(
        { error: (err as Error).message, path: req.path },
        'http_request_rejected',
      );
      res.status(401).json({ error: 'Invalid or expired token' });
    }
  };
}

export interface CollabRouterDeps {
  presenceHandler: PresenceHandler;
  documentAccess: DocumentAccessChecker;
  jwtSecret: string;
  logger: Logger;
}

export function createCollabRouter(deps: CollabRouterDeps): Router {
  const { presenceHandler, documentAccess, jwtSecret, logger } = deps;
  const router = Router();

  router.use('/api/v1/collab', createHttpAuthMiddleware(jwtSecret, logger));

  router.get('/api/v1/collab/documents/:id/presence', async (req, res) => {
    const { user, token } = res.locals.auth as AuthenticatedLocals;
    const documentId = req.params.id;

    const access = await documentAccess.check(documentId, token, user.userId);
    switch (access) {
      case 'allowed':
        res.json(presenceHandler.getPublicDocumentPresence(documentId));
        return;
      case 'not_found':
        res.status(404).json({ error: 'Document not found' });
        return;
      case 'denied':
        logger.warn({ documentId, userId: user.userId }, 'presence_access_denied');
        res.status(403).json({ error: 'Access denied' });
        return;
      default:
        res.status(503).json({ error: 'Unable to verify document access' });
    }
  });

  router.get('/api/v1/collab/documents', (_req, res) => {
    const { user } = res.locals.auth as AuthenticatedLocals;
    const activeDocuments = isAdmin(user)
      ? presenceHandler.getActiveDocuments()
      : presenceHandler.getActiveDocumentsForUser(user.userId);
    res.json({ documents: activeDocuments, count: activeDocuments.length });
  });

  return router;
}
