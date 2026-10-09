import { Router } from 'express';
import type { Logger } from 'pino';
import type { PresenceHandler } from '../handlers/presence';
import { extractBearerToken, isAdmin } from '../middleware/auth';
import { createHttpAuthMiddleware, getRequestUser } from '../middleware/http-auth';
import type { DocumentAccessChecker } from '../services/document-access';

type PresenceSource = Pick<
  PresenceHandler,
  'getDocumentPresence' | 'getActiveDocuments' | 'getActiveDocumentsForUser'
>;

export interface CollabApiOptions {
  jwtSecret: string;
  presenceHandler: PresenceSource;
  documentAccess: DocumentAccessChecker;
  logger: Logger;
}

export function createCollabApiRouter(options: CollabApiOptions): Router {
  const { jwtSecret, presenceHandler, documentAccess, logger } = options;
  const router = Router();

  router.use(createHttpAuthMiddleware(jwtSecret, logger));

  router.get('/documents/:id/presence', async (req, res) => {
    const user = getRequestUser(res);
    const documentId = req.params.id;

    if (!isAdmin(user)) {
      const bearer = extractBearerToken(req.headers.authorization);
      const access = await documentAccess.check(documentId, `Bearer ${bearer}`);
      if (access === 'unavailable') {
        res.status(503).json({ error: 'Document authorization unavailable' });
        return;
      }
      if (access === 'denied') {
        logger.warn({ documentId, userId: user.userId }, 'presence_access_denied');
        res.status(404).json({ error: 'Document not found' });
        return;
      }
    }

    res.json(presenceHandler.getDocumentPresence(documentId));
  });

  // Admins see every open document; everyone else only the documents they are in.
  router.get('/documents', (_req, res) => {
    const user = getRequestUser(res);
    const activeDocuments = isAdmin(user)
      ? presenceHandler.getActiveDocuments()
      : presenceHandler.getActiveDocumentsForUser(user.userId);
    res.json({ documents: activeDocuments, count: activeDocuments.length });
  });

  return router;
}
